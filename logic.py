
class Any(object):

  def __repr__(self):
    return '<ANY>'

ANY = Any()


class Context(object):

  def __init__(self):
    self.vars = {}
    self.varrs = {}
    self.changes = []
    self.waiting = {}

  def _SetRange(self, var, old_rng, new_rng):
    if len(new_rng) == 0:
      # Failure: prune early.
      return False
    def Undo():
      self.varrs[var] = old_rng
    self.changes.append(Undo)
    self.varrs[var] = new_rng
    # We could test for len(new_rng) == 1 here and run constraints,
    # but it is not necessary.
    return True

  def TrySetRange(self, var, rng):
    if var in self.vars:
      return self.vars[var] in rng
    old_rng = self.varrs.get(var, ANY)
    if old_rng is ANY:
      new_rng = frozenset(rng)
    else:
      new_rng = old_rng.intersection(rng)
      if len(new_rng) == len(old_rng):
        # No change: return early without running any constraints.
        return True
    return self._SetRange(var, old_rng, new_rng)

  def TryExclude(self, var, excl_list):
    if var in self.vars:
      return self.vars[var] not in excl_list
    old_rng = self.varrs.get(var, ANY)
    new_rng = old_rng.difference(excl_list)
    if len(new_rng) == len(old_rng):
      # No change: return early without running any constraints.
      return True
    return self._SetRange(var, old_rng, new_rng)

  # Tries to set var to i.
  # Returns True if successful.
  # Returns False if this produced a conflict.
  def TrySet(self, var, i):
    if var in self.vars:
      return self.vars[var] == i
    old_rng = self.varrs.get(var, ANY)
    if old_rng is not ANY and i not in old_rng:
      return False

    def Undo():
      self.varrs[var] = old_rng
      del self.vars[var]
    self.changes.append(Undo)
    self.varrs[var] = ANY
    self.vars[var] = i
    for constraint in self.waiting.get(var, []):
      status = constraint.RunConstraint(self)
      assert status in ('fail', 'done', 'skip'), status
      if status == 'fail':
        return False
    return True

  def Set(self, var, i, cont):
    if self.TrySet(var, i):
      cont()

  def IsSet(self, var):
    return var in self.vars

  def GetValue(self, var):
    return self.vars[var]

  def AddWaiter(self, var, func):
    self.waiting.setdefault(var, []).append(func)
    def Undo():
      self.waiting[var].remove(func)
    self.changes.append(Undo)

  def AddConstraint(self, con, cont):
    status = con.RunConstraint(self)
    if status != 'fail':
      if status != 'done':
        for var in con.var_list:
          self.AddWaiter(var, con)
      cont()

  def Choice(self):
    old_changes = self.changes
    self.changes = []
    def Restore():
      for undo in reversed(self.changes):
        undo()
      self.changes = old_changes
    return Restore


def Equal(var, i):
  def Func(ctx, cont):
    ctx.Set(var, i, cont)
  return Func

# Note that this is non-generative: it only works if var has already
# been assigned/constrained.
def NotEqual(var, i):
  def Func(ctx, cont):
    if ctx.TryExclude(var, [i]):
      cont()
  return Func

def InSet(var, values):
  as_set = set(values)
  def Func(ctx, cont):
    if ctx.TrySetRange(var, as_set):
      cont()
  return Func

def NotInSet(var, values):
  as_set = set(values)
  def Func(ctx, cont):
    if ctx.TryExclude(var, as_set):
      cont()
  return Func

def ForRange(var, upto):
  def Func(ctx, cont):
    if ctx.TrySetRange(var, xrange(upto)):
      cont()
  return Func

def Conj2(term1, term2):
  def Func(ctx, cont):
    term1(ctx, lambda: term2(ctx, cont))
  return Func

def Disj2(term1, term2):
  def Func(ctx, cont):
    restore = ctx.Choice()
    term1(ctx, cont)
    restore()
    term2(ctx, cont)
  return Func

def Pass(ctx, cont):
  cont()

def Fail(ctx, cont):
  pass

def Conj(*terms):
  return reduce(Conj2, terms, Pass)

def Disj(*terms):
  return reduce(Disj2, terms, Fail)


class EqualVarConstraint(object):

  def __init__(self, var1, var2):
    self.var1 = var1
    self.var2 = var2
    self.var_list = [var1, var2]

  def RunConstraint(self, ctx):
    if ctx.IsSet(self.var1):
      if not ctx.TrySet(self.var2, ctx.GetValue(self.var1)):
        return 'fail'
      return 'done'
    elif ctx.IsSet(self.var2):
      if not ctx.TrySet(self.var1, ctx.GetValue(self.var2)):
        return 'fail'
      return 'done'
    return 'skip'

# This could be implemented in terms of Apply().
def EqualVar(var1, var2):
  constraint = EqualVarConstraint(var1, var2)
  def Func(ctx, cont):
    ctx.AddConstraint(constraint, cont)
  return Func


class ApplyConstraint(object):

  def __init__(self, dest_var, func, arg_vars, args):
    self.dest_var = dest_var
    self.func = func
    self.arg_vars = arg_vars
    self.args = args
    self.var_list = [dest_var] + arg_vars

  def RunConstraint(self, ctx):
    if all(ctx.IsSet(var) for var in self.arg_vars):
      result = self.func([ctx.GetValue(var) for var in self.arg_vars],
                         *self.args)
      if not ctx.TrySet(self.dest_var, result):
        return 'fail'
      return 'done'
    elif ctx.IsSet(self.dest_var) and hasattr(self.func, 'rev'):
      values = self.func.rev(ctx.GetValue(self.dest_var), *self.args)
      if values is None:
        return 'fail'
      assert len(values) == len(self.arg_vars)
      for var, x in zip(self.arg_vars, values):
        if not ctx.TrySet(var, x):
          return 'fail'
      return 'done'
    return 'skip'

def Apply(dest_var, func, arg_vars, *args):
  constraint = ApplyConstraint(dest_var, func, arg_vars, args)
  def Func(ctx, cont):
    ctx.AddConstraint(constraint, cont)
  return Func


# Syntactic sugar.
def Switch(var, *branches):
  return Disj(*[Conj(Equal(var, x), code)
                for x, code in branches])


def GenerateAll(term, callback):
  ctx = Context()

  def Cont():
    var_list = sorted(var for var, rng in ctx.varrs.iteritems())
    def Rec(i):
      if i < len(var_list):
        var = var_list[i]
        rng = ctx.varrs.get(var, ANY)
        if rng is ANY:
          Rec(i + 1)
        else:
          for x in sorted(rng):
            restore = ctx.Choice()
            if ctx.TrySet(var, x):
              Rec(i + 1)
            restore()
      else:
        callback(ctx.vars.copy())
    Rec(0)

  term(ctx, Cont)
  # Sanity check: Check that constraints get undone correctly.
  for undo in reversed(ctx.changes):
    undo()
  ctx.changes = []
  for var, rng in ctx.varrs.iteritems():
    assert rng is ANY, (var, rng)
  for var, waiters in ctx.waiting.iteritems():
    assert waiters == [], var

def GetAll(term):
  got = []
  GenerateAll(term, got.append)
  return got


# Test cases

def assert_eq(x, y):
  if x != y:
    raise AssertionError('%r != %r' % (x, y))

assert_eq(GetAll(Conj(ForRange('x', 2),
                      ForRange('y', 2))),
          [{'x':0, 'y':0},
           {'x':0, 'y':1},
           {'x':1, 'y':0},
           {'x':1, 'y':1}])
# Check that Equal() works on an already-assigned variable.
assert_eq(GetAll(Conj(ForRange('x', 10),
                      Equal('x', 3))),
          [{'x': 3}])
# Check that Equal() can assign.
# Check that ForRange() checks the var.
assert_eq(GetAll(Conj(Equal('x', 3),
                      ForRange('x', 10))),
          [{'x': 3}])
# Test NotEqual().
assert_eq(GetAll(Conj(ForRange('x', 3),
                      NotEqual('x', 1))),
          [{'x': 0},
           {'x': 2}])
# Test EqualVar().
assert_eq(GetAll(Conj(ForRange('x', 2),
                      ForRange('y', 2),
                      EqualVar('x', 'y'))),
          [{'x':0, 'y':0},
           {'x':1, 'y':1}])
# Check that EqualVar() works when the vars are not set yet.
assert_eq(GetAll(Conj(EqualVar('x', 'y'),
                      Equal('x', 123))),
          [{'x':123, 'y':123}])
assert_eq(GetAll(Conj(EqualVar('x', 'y'),
                      Equal('y', 123))),
          [{'x':123, 'y':123}])

def Tuple(args):
  return tuple(args)
def TupleRev(arg):
  return arg
Tuple.rev = TupleRev

# Test Assign().
assert_eq(GetAll(Conj(ForRange('x', 2),
                      ForRange('y', 2),
                      Apply('z', tuple, ['x', 'y']))),
          [{'x':0, 'y':0, 'z':(0,0)},
           {'x':0, 'y':1, 'z':(0,1)},
           {'x':1, 'y':0, 'z':(1,0)},
           {'x':1, 'y':1, 'z':(1,1)}])
# Check that Assign() works before the arguments are set.
# It should store a constraint.
assert_eq(GetAll(Conj(Apply('z', tuple, ['x', 'y']),
                      Equal('x', 'foo'),
                      Equal('y', 'bar'))),
          [{'x':'foo', 'y':'bar', 'z':('foo', 'bar')}])
# Check that Assign() works in reverse.
assert_eq(GetAll(Conj(Equal('z', ('foo', 'bar')),
                      Apply('z', Tuple, ['x', 'y']))),
          [{'x':'foo', 'y':'bar', 'z':('foo', 'bar')}])
assert_eq(GetAll(Conj(Apply('z', Tuple, ['x', 'y']),
                      Equal('z', ('foo', 'bar')))),
          [{'x':'foo', 'y':'bar', 'z':('foo', 'bar')}])

def TestFunc(args):
  raise AssertionError()
def TestFuncRev(arg):
  return None
TestFunc.rev = TestFuncRev

# Reversing a function is allowed to fail.
assert_eq(GetAll(Conj(Apply('z', TestFunc, ['x']),
                      Equal('z', 123))),
          [])
assert_eq(GetAll(Conj(Equal('z', 123),
                      Apply('z', TestFunc, ['x']))),
          [])

# Test Disj().
assert_eq(GetAll(Conj(Disj(Equal('x', 'a'), Equal('x', 'b')),
                      Disj(Equal('y', 'c'), Equal('y', 'd')))),
          [{'x':'a', 'y':'c'},
           {'x':'a', 'y':'d'},
           {'x':'b', 'y':'c'},
           {'x':'b', 'y':'d'}])

# Test InSet().
assert_eq(GetAll(Conj(InSet('x', [1, 2]))),
          [{'x':1}, {'x':2}])
assert_eq(GetAll(Conj(Equal('x', 1),
                      InSet('x', [1, 2]))),
          [{'x':1}])
# Test NotInSet().
assert_eq(GetAll(Conj(InSet('x', [1, 2, 3, 4]),
                      NotInSet('x', [1, 3]))),
          [{'x':2}, {'x':4}])

# Test Pass.
assert_eq(GetAll(Conj(Equal('x', 1), Pass)), [{'x':1}])
# Test Fail.
assert_eq(GetAll(Conj(Equal('x', 1), Fail)), [])
