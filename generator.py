
import subprocess
import objdump


def Byte(x):
  return '%02x' % x


regs32 = (
  (0, 'eax'),
  (1, 'ecx'),
  (2, 'edx'),
  (3, 'ebx'),
  (4, 'esp'),
  (5, 'ebp'),
  (6, 'esi'),
  (7, 'edi'))

regs16 = (
  (0, 'ax'),
  (1, 'cx'),
  (2, 'dx'),
  (3, 'bx'),
  (4, 'sp'),
  (5, 'bp'),
  (6, 'si'),
  (7, 'di'))

regs8 = (
  (0, 'al'),
  (1, 'cl'),
  (2, 'dl'),
  (3, 'bl'),
  (4, 'ah'),
  (5, 'ch'),
  (6, 'dh'),
  (7, 'bh'))


def Sib(mod):
  for index_reg, index_regname in regs32:
    if index_reg == 4:
      # %esp is not accepted in the position '(reg, %esp)'.
      # In this context, register 4 is %eiz (an always-zero value).
      index_regname = 'eiz'
    for scale in (0, 1, 2, 3):
      # 5 is a special case and is not always %ebp.
      # %esi/%edi are missing from headings in table in doc.
      for base_reg, base_regname in regs32:
        if index_regname == 'eiz' and base_regname == 'esp' and scale == 0:
          index_result = ''
        else:
          index_result = '%s*%s' % (index_regname, 1 << scale)
        if base_reg == 5 and mod == 0:
          base_regname = ''
          extra = 'VALUE32'
          extra2 = ['XX'] * 4
        else:
          extra = ''
          extra2 = []
        parts = [base_regname, index_result, extra]
        yield [Byte((scale << 6) | (index_reg << 3) | base_reg)] + extra2, parts


def FormatMemAccess(parts):
  parts = [part for part in parts if part != '']
  return 'DWORD PTR [%s]' % '+'.join(parts)


def ModRM1(arg_regs):
  yield (0, 5, ['XX'] * 4, 'DWORD PTR ds:VALUE32')
  for mod, dispsize, disp_str in ((0, 0, ''),
                                  (1, 1, 'VALUE8'),
                                  (2, 4, 'VALUE32')):
    for reg2, regname2 in regs32:
      if reg2 == 4:
        # %esp is not accepted in this position.
        # 4 is a special value: adds SIB byte.
        continue
      if reg2 == 5 and mod == 0:
        continue
      yield (mod, reg2, ['XX'] * dispsize,
             FormatMemAccess([regname2, disp_str]))
    reg2 = 4
    for sib_bytes, desc in Sib(mod):
      yield (mod, reg2, sib_bytes + ['XX'] * dispsize,
             FormatMemAccess(desc + [disp_str]))
  mod = 3
  for reg2, regname2 in arg_regs:
    yield (mod, reg2, [], regname2)


def ModRM(arg_regs):
  for reg, regname in arg_regs:
    for mod, reg2, rest, desc in ModRM1(arg_regs):
      yield ([Byte((mod << 6) | (reg << 3) | reg2)] + rest, regname, desc)


def ModRMSingleArg(arg_regs, opcode):
  for mod, reg2, rest, desc in ModRM1(arg_regs):
    yield ([Byte((mod << 6) | (opcode << 3) | reg2)] + rest, desc)


def TrieNode(children):
  node = trie.Trie()
  node.children = children
  return node


def TrieOfList(bytes, node):
  for byte in reversed(bytes):
    node = TrieNode({byte: node})
  return node


class DftLabel(object):

  def __init__(self, key, value, next):
    self.key = key
    self.value = value
    self.next = next

def DftLabels(pairs, node):
  for key, value in pairs:
    node = DftLabel(key, value, node)
  return node


from memoize import Memoize

def TrieSize(start_node, expand_wildcards):
  @Memoize
  def Rec(node):
    if isinstance(node, DftLabel):
      return Rec(node.next)
    x = 0
    if node.accept:
      x += 1
    if expand_wildcards and 'XX' in node.children:
      return x + 256 * Rec(node.children['XX'])
    else:
      for child in node.children.itervalues():
        x += Rec(child)
      return x

  return Rec(start_node)


import trie

def NoMerge(x):
  raise Exception('Cannot merge %r' % x)


@Memoize
def ModRMNode(regs, immediate_size):
  nodes = []
  tail = TrieOfList(['XX'] * immediate_size, trie.AcceptNode)
  for bytes, reg_arg, rm_arg in ModRM(regs32):
    nodes.append(TrieOfList(bytes,
                            DftLabels([('reg_arg', reg_arg),
                                       ('rm_arg', rm_arg)], tail)))
  return trie.MergeMany(nodes, NoMerge)

def FlattenTrie(node, bytes=[], labels=[]):
  if isinstance(node, DftLabel):
    for result in FlattenTrie(node.next, bytes, labels + [node]):
      yield result
  else:
    if node.accept:
      yield (bytes, labels)
    for byte, next in sorted(node.children.iteritems()):
      for result in FlattenTrie(next, bytes + [byte], labels):
        yield result

def GetRoot():
  top_nodes = []

  def Add(bytes, instr_name, args):
    bytes = bytes.split()
    top_nodes.append(TrieOfList(bytes, DftLabels([('instr_name', instr_name),
                                                  ('args', args)],
                                                 ModRMNode(regs32, 0))))

  Add('01', 'add', ['rm', 'reg'])
  Add('03', 'add', ['reg', 'rm'])
  return trie.MergeMany(top_nodes, NoMerge)

def GetAll():
  for bytes, labels in FlattenTrie(GetRoot()):
    args = dict((label.key, label.value) for label in labels)
    i_args = ', '.join([args['%s_arg' % arg] for arg in args['args']])
    instr = '%s %s' % (args['instr_name'], i_args)
    yield (bytes, instr)

import objdump_check

print TrieSize(GetRoot(), False)

objdump_check.DisassembleTest(GetAll, bits=32)
