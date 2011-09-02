
import re
import subprocess
import sys


def MapWildcard(byte):
  if byte == 'XX':
    return '11'
  else:
    return byte


def DisassembleTestCallback(get_instructions, bits):
  asm_fh = open('tmp.S', 'w')
  list_fh = open('tmp.list', 'w')
  count = [0]

  def Callback(bytes, desc):
    escaped_bytes = ''.join('\\x' + MapWildcard(byte) for byte in bytes)
    asm_fh.write('.ascii "%s"\n' % escaped_bytes)
    list_fh.write('%s:%s\n' % (' '.join(bytes), desc))
    count[0] += 1

  get_instructions(Callback)
  print 'Checking %i instructions...' % count[0]
  # Add a final instruction otherwise we do not catch length
  # mismatches on the last input instruction.
  Callback(['90'], 'nop')
  asm_fh.close()
  list_fh.close()
  subprocess.check_call(['gcc', '-c', '-m%i' % bits, 'tmp.S', '-o', 'tmp.o'])
  CrossCheck('tmp.o', 'tmp.list')


whitespace_regexp = re.compile('\s+')
comment_regexp = re.compile('\s+#.*$')
jump_regexp = re.compile('^(jn?[a-z]{1,2}|calll|jmp[lw]?|je?cxz) 0x[0-9a-f]+$')


def NormaliseObjdumpDisasm(disasm):
  # Canonicalise whitespace.
  disasm = whitespace_regexp.sub(' ', disasm)
  # Remove comments.
  disasm = comment_regexp.sub('', disasm)
  # objdump puts in trailing whitespace sometimes.
  disasm = disasm.rstrip(' ')
  # Canonicalise jump targets.
  disasm = jump_regexp.sub('\\1 JUMP_DEST', disasm)
  disasm = (disasm
            .replace('0x1111111111111111', 'VALUE64')
            .replace('0x11111111', 'VALUE32')
            .replace('0x1111', 'VALUE16')
            .replace('0x11', 'VALUE8')
            .replace(',', ', '))
  # gas accepts a ".s" suffix to indicate a non-canonical
  # reversed-operands encoding.  With "-M suffix", objdump prints
  # this.
  disasm = disasm.replace('.s ', ' ')
  return disasm


def ReadObjdump(obj_file):
  proc = subprocess.Popen(['objdump', '-M', 'intel', '--prefix-addresses',
                           '-d', obj_file],
                          stdout=subprocess.PIPE)
  regexp = re.compile('0x([0-9a-f]+)\s*')
  for line in proc.stdout:
    match = regexp.match(line)
    if match is not None:
      addr = int(match.group(1), 16)
      disasm = line[match.end():]
      yield addr, disasm
  assert proc.wait() == 0, proc.wait()


def ReadListFile(fh):
  for line in fh:
    bytes, desc = line.rstrip('\n').split(':', 1)
    yield bytes.split(' '), desc


def CrossCheck(obj_file, list_file):
  objdump_iter = ReadObjdump('tmp.o')
  expected_addr = 0
  prev_length = 0
  for index, (bytes, desc) in enumerate(ReadListFile(open('tmp.list'))):
    got_addr, disasm_orig = objdump_iter.next()
    if got_addr != expected_addr:
      # This only catches mismatches on the previous instruction,
      # which is why we added an extra final instruction earlier.
      print 'Length mismatch on previous instruction: got %i, expected %i' % (
          prev_length + got_addr - expected_addr,
          prev_length)
      break
    expected_addr += len(bytes)
    prev_length = len(bytes)

    disasm = NormaliseObjdumpDisasm(disasm_orig)
    # Remove trailing space from our zero-arg instructions, e.g. 'nop'.
    # TODO: Don't put the trailing space in.
    desc = desc.rstrip(' ')
    if desc.startswith('TODO'):
      # Some instructions' disassembly is not done properly yet.  We
      # are only checking their encoding length.
      continue
    if desc != disasm:
      print 'Mismatch (%i): %r != %r (%r) (%s)' % (
        index, desc, disasm, disasm_orig, ' '.join(bytes))


def DisassembleTest(get_instructions, bits):
  def Func(callback):
    for bytes, desc in get_instructions():
      callback(bytes, desc)
  DisassembleTestCallback(Func, bits)


def Main(args):
  for filename in args:
    DisassembleTest(lambda: ReadListFile(open(filename, 'r')), 32)


if __name__ == '__main__':
  Main(sys.argv[1:])
