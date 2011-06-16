
import time

import constraint_gen
import logic
import trie


NOT_FOUND = object()


def Memoize(func):
  cache = {}
  def Wrapper(*args):
    value = cache.get(args, NOT_FOUND)
    if value is NOT_FOUND:
      value = func(*args)
      cache[args] = value
    return value
  return Wrapper


def GetApplyConstraint(ctx, var, func):
  for con in ctx.waiting.get(var, []):
    if (isinstance(con, logic.ApplyConstraint) and
        con.func == func and
        con.dest_var == var):
      yield con


def GetVarValues(ctx, var):
  if var in ctx.vars:
    return [ctx.vars[var]]
  else:
    return sorted(ctx.varrs[var])


def Permutations(items):
  if len(items) == 0:
    yield []
  else:
    for x in items[0]:
      for xs in Permutations(items[1:]):
        yield [x] + xs


# TODO: Don't convert ints to strings, because this slows things down.
def FormatByte(byte):
  return '%02x' % byte


def TriePrepend(bytes, tail_trie):
  children = {}
  for byte in bytes:
    children[FormatByte(byte)] = tail_trie
  return trie.MakeInterned(children, False)


@Memoize
def TrieCatPrepend(vals, sizes, tail_trie):
  bytes = [constraint_gen.CatBits(perm, sizes)
           for perm in Permutations(vals)]
  return TriePrepend(bytes, tail_trie)


def FollowByte(ctx, var, tail_trie):
  if var in ctx.vars:
    return TriePrepend([ctx.vars[var]], tail_trie)
  for con in GetApplyConstraint(ctx, var, constraint_gen.CatBits):
    vals = tuple(tuple(sorted(GetVarValues(ctx, arg))) for arg in con.arg_vars)
    sizes = tuple(con.args[0])
    return TrieCatPrepend(vals, sizes, tail_trie)
  raise AssertionError('FollowByte failed')


def FollowBytes(ctx, var):
  if var in ctx.vars:
    return TrieOfList(tuple(ctx.vars[var]))
  for con in ctx.waiting.get(var, []):
    if isinstance(con, logic.EqualVarConstraint) and con.var1 == var:
      return FollowBytes(ctx, con.var2)
  for con in GetApplyConstraint(ctx, var, constraint_gen.PrependByte):
    return FollowByte(ctx, con.arg_vars[0],
                      FollowBytes(ctx, con.arg_vars[1]))
  raise AssertionError('FollowBytes failed')


@Memoize
def TrieOfList(bytes):
  node = trie.AcceptNode
  for byte in reversed(bytes):
    node = trie.MakeInterned({byte: node}, False)
  return node


def Time(func):
  t0 = time.time()
  r = func()
  t1 = time.time()
  print '%s took %fs' % (func, t1 - t0)
  return r


class Generator(object):

  def __init__(self):
    self.ctx = logic.Context()
    self.got_nodes = []
    self.count = 0
    self.start_time = time.time()
    self.next_time = self.start_time + 1

  def Add(self):
    self.got_nodes.append(FollowBytes(self.ctx, 'bytes'))
    # Print stats
    self.count += 1
    time_now = time.time()
    if time_now > self.next_time:
      taken = time_now - self.start_time
      print '%i templates in %.1fs; %.2fs template/sec' % (
          self.count, taken, self.count / taken)
      self.next_time += 1

  def Run(self, term):
    term(self.ctx, self.Add)
    return Time(lambda: trie.MergeMany(self.got_nodes))


def Main():
  generator = Generator()
  root = generator.Run(constraint_gen.Encode)
  trie.WriteToFile('new.trie', root)


if __name__ == '__main__':
  Main()
