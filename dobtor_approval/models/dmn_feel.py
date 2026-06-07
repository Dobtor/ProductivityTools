# -*- coding: utf-8 -*-
# Copyright 2026 Dobtor Systems Integration — License LGPL-3
"""FEEL 子集求值引擎（純 Python，stdlib only）。

設計原則（DESIGN_DMN.md §4）：
- 核心 lexer / parser / interpreter 為 **pure functions，不 import odoo** →
  可獨立單元測試（直接 `python3 dmn_feel.py`）。models 層另以薄包裝呼叫。
- 無 eval / exec；函式白名單；無屬性逃逸（禁 `__...__`）；步數/深度上限。

涵蓋：
- Unary test（規則格 input entry）：`-`、比較（`< <= > >= = !=`）、區間 `[a..b] (a..b) [a..b) (a..b]`、
  清單（`a, b, c` → OR）、`not(...)`、字面等值（含 list 成員）。
- 運算式（output / literal expression）：算術 `+ - * / **`、字串串接、比較、`and/or/not`、
  `if … then … else …`、變數 / 路徑、白名單函式。
- 型別：Decimal / str / bool / datetime.date / datetime.time / datetime.timedelta / list / dict(context) / None。
"""
from decimal import Decimal, InvalidOperation, getcontext
import datetime
import re

getcontext().prec = 28

_MAX_STEPS = 100000   # 求值步數上限（防惡意巢狀）


class FeelError(Exception):
    """FEEL 語法 / 求值錯誤。"""
    pass


# ===========================================================================
# Lexer
# ===========================================================================
_KEYWORDS = {'true', 'false', 'null', 'and', 'or', 'not', 'if', 'then', 'else'}

# 順序重要：長運算子在前
_TOKEN_SPEC = [
    ('WS',      r'[ \t\r\n]+'),
    ('NUMBER',  r'\d+\.\d+|\d+'),
    ('STRING',  r'"(?:[^"\\]|\\.)*"'),
    ('RANGE',   r'\.\.'),
    ('OP',      r'\*\*|<=|>=|!=|<|>|=|\+|-|\*|/'),
    ('PUNC',    r'[\(\)\[\]\{\},\.:]'),
    # NAME 允許底線、英數、CJK
    ('NAME',    r'[A-Za-z_一-鿿][A-Za-z0-9_一-鿿]*'),
]
_TOKEN_RE = re.compile('|'.join('(?P<%s>%s)' % p for p in _TOKEN_SPEC))


class _Tok(object):
    __slots__ = ('kind', 'val', 'pos')

    def __init__(self, kind, val, pos):
        self.kind = kind
        self.val = val
        self.pos = pos

    def __repr__(self):
        return '%s(%r)' % (self.kind, self.val)


def tokenize(src):
    """字串 → token 串列（含結尾 EOF）。"""
    toks = []
    pos = 0
    n = len(src)
    while pos < n:
        m = _TOKEN_RE.match(src, pos)
        if not m:
            raise FeelError('無法解析的字元 @%d: %r' % (pos, src[pos:pos + 8]))
        kind = m.lastgroup
        val = m.group()
        pos = m.end()
        if kind == 'WS':
            continue
        if kind == 'NAME' and val in _KEYWORDS:
            toks.append(_Tok('KW', val, m.start()))
        else:
            toks.append(_Tok(kind, val, m.start()))
    toks.append(_Tok('EOF', '', pos))
    return toks


# ===========================================================================
# AST 節點
# ===========================================================================
class Lit(object):
    __slots__ = ('value',)

    def __init__(self, value):
        self.value = value


class Name(object):
    __slots__ = ('qname',)

    def __init__(self, qname):
        self.qname = qname


class Path(object):
    __slots__ = ('base', 'attr')

    def __init__(self, base, attr):
        self.base = base
        self.attr = attr


class Bin(object):
    __slots__ = ('op', 'l', 'r')

    def __init__(self, op, l, r):
        self.op = op
        self.l = l
        self.r = r


class Un(object):
    __slots__ = ('op', 'x')

    def __init__(self, op, x):
        self.op = op
        self.x = x


class IfElse(object):
    __slots__ = ('cond', 'then', 'els')

    def __init__(self, cond, then, els):
        self.cond = cond
        self.then = then
        self.els = els


class FunCall(object):
    __slots__ = ('name', 'args')

    def __init__(self, name, args):
        self.name = name
        self.args = args


class ListLit(object):
    __slots__ = ('items',)

    def __init__(self, items):
        self.items = items


class Interval(object):
    """區間：low_open/high_open 為 True 表示開端點（不含）。"""
    __slots__ = ('low_open', 'low', 'high', 'high_open')

    def __init__(self, low_open, low, high, high_open):
        self.low_open = low_open
        self.low = low
        self.high = high
        self.high_open = high_open


# Unary-test 專用節點
class AnyTest(object):
    """`-`：永遠為真。"""
    __slots__ = ()


class CmpTest(object):
    """比較測試：`<op> endpoint`，以輸入值（?）為左運算元。"""
    __slots__ = ('op', 'endpoint')

    def __init__(self, op, endpoint):
        self.op = op
        self.endpoint = endpoint


class EqTest(object):
    """等值 / 成員測試：? = expr（expr 為 list 時取成員）。"""
    __slots__ = ('expr',)

    def __init__(self, expr):
        self.expr = expr


class IntervalTest(object):
    __slots__ = ('interval',)

    def __init__(self, interval):
        self.interval = interval


class NotTest(object):
    __slots__ = ('tests',)

    def __init__(self, tests):
        self.tests = tests


class OrTests(object):
    """逗號分隔的多個 positiveUnaryTest → 命中其一即真。"""
    __slots__ = ('tests',)

    def __init__(self, tests):
        self.tests = tests


# ===========================================================================
# Parser（recursive descent）
# ===========================================================================
class _Parser(object):
    def __init__(self, toks):
        self.toks = toks
        self.i = 0

    def _peek(self):
        return self.toks[self.i]

    def _next(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def _at(self, kind, val=None):
        t = self.toks[self.i]
        return t.kind == kind and (val is None or t.val == val)

    def _eat(self, kind, val=None):
        t = self.toks[self.i]
        if t.kind != kind or (val is not None and t.val != val):
            raise FeelError('預期 %s%s，得到 %r' % (
                kind, ('/' + val) if val else '', t))
        self.i += 1
        return t

    # ---- 運算式 ----
    def parse_expression(self):
        node = self._expr()
        if not self._at('EOF'):
            raise FeelError('運算式結尾有殘留 token: %r' % (self._peek(),))
        return node

    def _expr(self):
        if self._at('KW', 'if'):
            return self._if()
        return self._or()

    def _if(self):
        self._eat('KW', 'if')
        cond = self._or()
        self._eat('KW', 'then')
        then = self._expr()
        self._eat('KW', 'else')
        els = self._expr()
        return IfElse(cond, then, els)

    def _or(self):
        node = self._and()
        while self._at('KW', 'or'):
            self._next()
            node = Bin('or', node, self._and())
        return node

    def _and(self):
        node = self._cmp()
        while self._at('KW', 'and'):
            self._next()
            node = Bin('and', node, self._cmp())
        return node

    def _cmp(self):
        node = self._add()
        while self._at('OP') and self._peek().val in ('=', '!=', '<', '<=', '>', '>='):
            op = self._next().val
            node = Bin(op, node, self._add())
        return node

    def _add(self):
        node = self._mul()
        while self._at('OP') and self._peek().val in ('+', '-'):
            op = self._next().val
            node = Bin(op, node, self._mul())
        return node

    def _mul(self):
        node = self._pow()
        while self._at('OP') and self._peek().val in ('*', '/'):
            op = self._next().val
            node = Bin(op, node, self._pow())
        return node

    def _pow(self):
        node = self._unary()
        if self._at('OP', '**'):
            self._next()
            return Bin('**', node, self._unary())
        return node

    def _unary(self):
        if self._at('OP', '-'):
            self._next()
            return Un('-', self._unary())
        if self._at('KW', 'not'):
            self._next()
            self._eat('PUNC', '(')
            x = self._expr()
            self._eat('PUNC', ')')
            return Un('not', x)
        return self._postfix()

    def _postfix(self):
        node = self._primary()
        while self._at('PUNC', '.'):
            self._next()
            attr = self._name_words()
            node = Path(node, attr)
        return node

    def _name_words(self):
        """連續 NAME → 以空白接合的限定名（FEEL 允許多詞名）。"""
        parts = [self._eat('NAME').val]
        while self._at('NAME'):
            parts.append(self._next().val)
        return ' '.join(parts)

    def _primary(self):
        t = self._peek()
        if t.kind == 'NUMBER':
            self._next()
            return Lit(Decimal(t.val))
        if t.kind == 'STRING':
            self._next()
            return Lit(_unescape(t.val))
        if t.kind == 'KW' and t.val in ('true', 'false'):
            self._next()
            return Lit(t.val == 'true')
        if t.kind == 'KW' and t.val == 'null':
            self._next()
            return Lit(None)
        if t.kind == 'PUNC' and t.val == '(':
            self._next()
            node = self._expr()
            self._eat('PUNC', ')')
            return node
        if t.kind == 'PUNC' and t.val == '[':
            return self._list_or_interval()
        if t.kind == 'NAME':
            qname = self._name_words()
            if self._at('PUNC', '('):
                return self._call(qname)
            return Name(qname)
        raise FeelError('未預期的 token: %r' % (t,))

    def _list_or_interval(self):
        self._eat('PUNC', '[')
        first = self._expr()
        if self._at('RANGE'):
            self._next()
            high = self._expr()
            close = self._eat('PUNC')
            high_open = (close.val == ')')
            if close.val not in (']', ')'):
                raise FeelError('區間結尾須為 ] 或 )')
            return Interval(False, first, high, high_open)
        items = [first]
        while self._at('PUNC', ','):
            self._next()
            items.append(self._expr())
        self._eat('PUNC', ']')
        return ListLit(items)

    def _call(self, name):
        self._eat('PUNC', '(')
        args = []
        if not self._at('PUNC', ')'):
            args.append(self._expr())
            while self._at('PUNC', ','):
                self._next()
                args.append(self._expr())
        self._eat('PUNC', ')')
        return FunCall(name, args)

    # ---- Unary tests ----
    def parse_unary_tests(self):
        # '-' → AnyTest
        if self._at('OP', '-') and self.toks[self.i + 1].kind == 'EOF':
            self._next()
            node = AnyTest()
        elif self._at('KW', 'not'):
            self._next()
            self._eat('PUNC', '(')
            node = NotTest(self._positive_unary_tests())
            self._eat('PUNC', ')')
        else:
            tests = self._positive_unary_tests()
            node = tests[0] if len(tests) == 1 else OrTests(tests)
        if not self._at('EOF'):
            raise FeelError('unary test 結尾有殘留: %r' % (self._peek(),))
        return node

    def _positive_unary_tests(self):
        tests = [self._positive_unary_test()]
        while self._at('PUNC', ','):
            self._next()
            tests.append(self._positive_unary_test())
        return tests

    def _positive_unary_test(self):
        t = self._peek()
        if t.kind == 'OP' and t.val in ('<', '<=', '>', '>=', '=', '!='):
            op = self._next().val
            return CmpTest(op, self._add())
        if t.kind == 'PUNC' and t.val in ('[', '('):
            saved = self.i
            try:
                return IntervalTest(self._interval())
            except FeelError:
                self.i = saved
        return EqTest(self._expr())

    def _interval(self):
        open_tok = self._eat('PUNC')
        if open_tok.val not in ('[', '('):
            raise FeelError('區間須以 [ 或 ( 起始')
        low_open = (open_tok.val == '(')
        low = self._add()
        self._eat('RANGE')
        high = self._add()
        close = self._eat('PUNC')
        if close.val not in (']', ')'):
            raise FeelError('區間須以 ] 或 ) 結束')
        high_open = (close.val == ')')
        return Interval(low_open, low, high, high_open)


def _unescape(s):
    return (s[1:-1]
            .replace('\\"', '"').replace('\\n', '\n')
            .replace('\\t', '\t').replace('\\\\', '\\'))


def parse(src):
    return _Parser(tokenize(src)).parse_expression()


def parse_unary(src):
    return _Parser(tokenize(src)).parse_unary_tests()


# ===========================================================================
# Interpreter
# ===========================================================================
class _Ctr(object):
    __slots__ = ('n',)

    def __init__(self):
        self.n = 0

    def tick(self):
        self.n += 1
        if self.n > _MAX_STEPS:
            raise FeelError('求值步數超過上限')


def _num(x):
    if isinstance(x, bool):
        raise FeelError('期望數值，得到 boolean')
    if isinstance(x, Decimal):
        return x
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        return Decimal(str(x))
    if isinstance(x, str):
        try:
            return Decimal(x)
        except InvalidOperation:
            raise FeelError('無法轉為數值: %r' % (x,))
    raise FeelError('無法轉為數值: %r' % (x,))


def _lookup(ctx, qname):
    if qname in ctx:
        return ctx[qname]
    raise FeelError('未定義變數: %s' % qname)


def _member(base, attr):
    if attr.startswith('__'):
        raise FeelError('禁止存取: %s' % attr)
    if isinstance(base, dict):
        if attr in base:
            return base[attr]
        raise FeelError('context 無鍵: %s' % attr)
    if hasattr(base, attr):
        return getattr(base, attr)
    raise FeelError('無法存取屬性: %s' % attr)


def _eval(node, ctx, ctr):
    ctr.tick()
    k = node.__class__
    if k is Lit:
        return node.value
    if k is Name:
        return _lookup(ctx, node.qname)
    if k is Path:
        return _member(_eval(node.base, ctx, ctr), node.attr)
    if k is ListLit:
        return [_eval(it, ctx, ctr) for it in node.items]
    if k is Un:
        if node.op == '-':
            return -_num(_eval(node.x, ctx, ctr))
        if node.op == 'not':
            return not _truthy(_eval(node.x, ctx, ctr))
    if k is IfElse:
        if _truthy(_eval(node.cond, ctx, ctr)):
            return _eval(node.then, ctx, ctr)
        return _eval(node.els, ctx, ctr)
    if k is FunCall:
        fn = _BUILTINS.get(node.name)
        if fn is None:
            raise FeelError('未知函式: %s' % node.name)
        return fn([_eval(a, ctx, ctr) for a in node.args], ctx)
    if k is Bin:
        return _eval_bin(node, ctx, ctr)
    if k is Interval:
        # 區間作為值（少見）：回傳描述 dict
        return {'__interval__': True,
                'low': _eval(node.low, ctx, ctr),
                'high': _eval(node.high, ctx, ctr),
                'low_open': node.low_open, 'high_open': node.high_open}
    raise FeelError('無法求值節點: %r' % (k,))


def _truthy(v):
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    raise FeelError('期望 boolean，得到 %r' % (v,))


def _eval_bin(node, ctx, ctr):
    op = node.op
    if op == 'and':
        return _truthy(_eval(node.l, ctx, ctr)) and _truthy(_eval(node.r, ctx, ctr))
    if op == 'or':
        return _truthy(_eval(node.l, ctx, ctr)) or _truthy(_eval(node.r, ctx, ctr))
    l = _eval(node.l, ctx, ctr)
    r = _eval(node.r, ctx, ctr)
    if op == '+':
        if isinstance(l, str) or isinstance(r, str):
            return _to_str(l) + _to_str(r)
        return _num(l) + _num(r)
    if op == '-':
        return _num(l) - _num(r)
    if op == '*':
        return _num(l) * _num(r)
    if op == '/':
        rr = _num(r)
        if rr == 0:
            raise FeelError('除以零')
        return _num(l) / rr
    if op == '**':
        return _num(l) ** _num(r)
    if op == '=':
        return _eq(l, r)
    if op == '!=':
        return not _eq(l, r)
    if op in ('<', '<=', '>', '>='):
        return _cmp(op, l, r)
    raise FeelError('未知運算子: %s' % op)


def _to_str(v):
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if v is None:
        return ''
    if isinstance(v, Decimal):
        return format(v.normalize(), 'f')
    return str(v)


def _eq(l, r):
    lb, rb = isinstance(l, bool), isinstance(r, bool)
    if lb or rb:
        return lb and rb and l == r   # boolean 僅與 boolean 相等（避免 true == 1）
    if _is_num(l) and _is_num(r):
        return _num(l) == _num(r)
    return l == r


def _is_num(v):
    return isinstance(v, (Decimal, int)) and not isinstance(v, bool)


def _cmp(op, l, r):
    if _is_num(l) and _is_num(r):
        l, r = _num(l), _num(r)
    try:
        if op == '<':
            return l < r
        if op == '<=':
            return l <= r
        if op == '>':
            return l > r
        if op == '>=':
            return l >= r
    except TypeError:
        raise FeelError('無法比較: %r %s %r' % (l, op, r))


# ---- 白名單函式 ----
def _iso_duration(s):
    m = re.match(r'^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$', s)
    if not m:
        raise FeelError('無效 duration: %r' % (s,))
    d, h, mi, se = (int(x) if x else 0 for x in m.groups())
    return datetime.timedelta(days=d, hours=h, minutes=mi, seconds=se)


def _b_date(args, ctx):
    if len(args) == 1 and isinstance(args[0], str):
        return datetime.date.fromisoformat(args[0])
    if len(args) == 3:
        return datetime.date(int(_num(args[0])), int(_num(args[1])), int(_num(args[2])))
    raise FeelError('date() 參數錯誤')


def _b_time(args, ctx):
    if len(args) == 1 and isinstance(args[0], str):
        return datetime.time.fromisoformat(args[0])
    raise FeelError('time() 參數錯誤')


def _require_list(v, fn):
    if not isinstance(v, list):
        raise FeelError('%s 期望 list' % fn)
    return v


_BUILTINS = {
    'date':         _b_date,
    'time':         _b_time,
    'duration':     lambda a, c: _iso_duration(a[0]),
    'today':        lambda a, c: c.get('__today__') or datetime.date.today(),
    'now':          lambda a, c: c.get('__now__') or datetime.datetime.now(),
    'string':       lambda a, c: _to_str(a[0]),
    'number':       lambda a, c: _num(a[0]),
    'upper':        lambda a, c: a[0].upper(),
    'lower':        lambda a, c: a[0].lower(),
    'contains':     lambda a, c: a[1] in a[0],
    'starts with':  lambda a, c: a[0].startswith(a[1]),
    'ends with':    lambda a, c: a[0].endswith(a[1]),
    'substring':    lambda a, c: (a[0][int(_num(a[1])) - 1:
                                       (int(_num(a[1])) - 1 + int(_num(a[2]))) if len(a) > 2 else None]),
    'abs':          lambda a, c: abs(_num(a[0])),
    'floor':        lambda a, c: Decimal(int(_num(a[0]).to_integral_value(rounding='ROUND_FLOOR'))),
    'ceiling':      lambda a, c: Decimal(int(_num(a[0]).to_integral_value(rounding='ROUND_CEILING'))),
    'modulo':       lambda a, c: _num(a[0]) % _num(a[1]),
    'count':        lambda a, c: Decimal(len(_require_list(a[0], 'count'))),
    'sum':          lambda a, c: sum((_num(x) for x in _require_list(a[0], 'sum')), Decimal(0)),
    'min':          lambda a, c: min(_require_list(a[0], 'min')),
    'max':          lambda a, c: max(_require_list(a[0], 'max')),
    'list contains': lambda a, c: a[1] in _require_list(a[0], 'list contains'),
}


# ===========================================================================
# 對外 API
# ===========================================================================
def evaluate(src_or_ast, ctx=None):
    """求值一段 FEEL 運算式，回傳 Python 值。

    ctx：變數環境 dict（binding 注入的 record 欄位、上游決策輸出、常數）。
    可選特殊鍵：`__today__` / `__now__` 供決定性測試覆寫。
    """
    ctx = ctx or {}
    ast = src_or_ast if not isinstance(src_or_ast, str) else parse(src_or_ast)
    return _eval(ast, ctx, _Ctr())


def unary_test(src_or_ast, value, ctx=None):
    """以 value 為輸入（FEEL 的 ?），判斷是否命中 unary test，回傳 bool。"""
    ctx = dict(ctx or {})
    ast = src_or_ast if not isinstance(src_or_ast, str) else parse_unary(src_or_ast)
    return _test(ast, value, ctx, _Ctr())


def _test(node, value, ctx, ctr):
    ctr.tick()
    k = node.__class__
    if k is AnyTest:
        return True
    if k is OrTests:
        return any(_test(t, value, ctx, ctr) for t in node.tests)
    if k is NotTest:
        return not any(_test(t, value, ctx, ctr) for t in node.tests)
    if k is CmpTest:
        ep = _eval(node.endpoint, ctx, ctr)
        if node.op == '=':
            return _eq(value, ep)
        if node.op == '!=':
            return not _eq(value, ep)
        return _cmp(node.op, value, ep)
    if k is IntervalTest:
        return _in_interval(value, node.interval, ctx, ctr)
    if k is EqTest:
        ev = _eval(node.expr, ctx, ctr)
        if isinstance(ev, list):
            return value in ev
        return _eq(value, ev)
    raise FeelError('非法 unary test 節點: %r' % (k,))


def _in_interval(value, iv, ctx, ctr):
    low = _eval(iv.low, ctx, ctr)
    high = _eval(iv.high, ctx, ctr)
    lo_ok = _cmp('>', value, low) if iv.low_open else _cmp('>=', value, low)
    hi_ok = _cmp('<', value, high) if iv.high_open else _cmp('<=', value, high)
    return lo_ok and hi_ok


# ===========================================================================
# 自由變數擷取（發佈校驗用：找出運算式引用了哪些變數名）
# ===========================================================================
def free_names(src, is_unary=False):
    """回傳運算式 / unary test 引用的頂層變數名集合（不含函式名、路徑子層）。"""
    try:
        ast = parse_unary(src) if is_unary else parse(src)
    except FeelError:
        return set()
    out = set()
    _walk_names(ast, out)
    return out


def _walk_names(node, out):
    k = node.__class__
    if k is Name:
        out.add(node.qname)
    elif k is Path:
        _walk_names(node.base, out)        # 只記路徑根
    elif k is Bin:
        _walk_names(node.l, out)
        _walk_names(node.r, out)
    elif k is Un:
        _walk_names(node.x, out)
    elif k is IfElse:
        _walk_names(node.cond, out)
        _walk_names(node.then, out)
        _walk_names(node.els, out)
    elif k is FunCall:
        for a in node.args:
            _walk_names(a, out)
    elif k is ListLit:
        for it in node.items:
            _walk_names(it, out)
    elif k is Interval:
        _walk_names(node.low, out)
        _walk_names(node.high, out)
    elif k in (CmpTest,):
        _walk_names(node.endpoint, out)
    elif k in (EqTest,):
        _walk_names(node.expr, out)
    elif k is IntervalTest:
        _walk_names(node.interval, out)
    elif k in (NotTest, OrTests):
        for t in node.tests:
            _walk_names(t, out)


# ===========================================================================
# Standalone 單元測試（python3 dmn_feel.py）
# ===========================================================================
def _selftest():
    D = Decimal
    ok = 0

    def chk(got, exp, label):
        nonlocal ok
        if got != exp:
            raise AssertionError('%s：期望 %r 得到 %r' % (label, exp, got))
        ok += 1

    # 運算式
    chk(evaluate('1 + 2 * 3'), D(7), 'arith')
    chk(evaluate('(1 + 2) * 3'), D(9), 'paren')
    chk(evaluate('2 ** 10'), D(1024), 'pow')
    chk(evaluate('10 / 4'), D('2.5'), 'div')
    chk(evaluate('"a" + "b"'), 'ab', 'concat')
    chk(evaluate('amount * 0.05', {'amount': D(60000)}), D('3000.00'), 'var')
    chk(evaluate('if x > 5 then "big" else "small"', {'x': D(9)}), 'big', 'if')
    chk(evaluate('if x > 5 then "big" else "small"', {'x': D(3)}), 'small', 'else')
    chk(evaluate('true and false'), False, 'and')
    chk(evaluate('true or false'), True, 'or')
    chk(evaluate('not(true)'), False, 'not')
    chk(evaluate('3 = 3'), True, 'eq')
    chk(evaluate('3 != 4'), True, 'neq')
    chk(evaluate('"差旅" = "差旅"'), True, 'cjk-eq')
    chk(evaluate('true = true'), True, 'bool-eq')
    chk(evaluate('true = 1'), False, 'bool-strict')
    chk(evaluate('1 = 1'), True, 'num-eq')
    # 函式
    chk(evaluate('upper("abc")'), 'ABC', 'upper')
    chk(evaluate('contains("hello", "ell")'), True, 'contains')
    chk(evaluate('starts with("hello", "he")'), True, 'starts')
    chk(evaluate('substring("hello", 2, 3)'), 'ell', 'substr')
    chk(evaluate('abs(0 - 7)'), D(7), 'abs')
    chk(evaluate('floor(2.9)'), D(2), 'floor')
    chk(evaluate('ceiling(2.1)'), D(3), 'ceiling')
    chk(evaluate('sum(items)', {'items': [D(1), D(2), D(3)]}), D(6), 'sum')
    chk(evaluate('count(items)', {'items': [1, 2]}), D(2), 'count')
    chk(evaluate('list contains(items, 2)', {'items': [D(1), D(2)]}), True, 'listcontains')
    chk(evaluate('date("2026-06-07")'), datetime.date(2026, 6, 7), 'date')
    chk(evaluate('date("2026-06-07") < date("2026-12-31")'), True, 'date-cmp')
    # 路徑
    chk(evaluate('a.b', {'a': {'b': D(5)}}), D(5), 'path')
    # Unary tests
    chk(unary_test('-', D(123)), True, 'u-any')
    chk(unary_test('>= 50000', D(60000)), True, 'u-ge')
    chk(unary_test('>= 50000', D(40000)), False, 'u-ge2')
    chk(unary_test('< 100', D(50)), True, 'u-lt')
    chk(unary_test('[1000..5000]', D(3000)), True, 'u-interval')
    chk(unary_test('[1000..5000]', D(5000)), True, 'u-interval-closed')
    chk(unary_test('[1000..5000)', D(5000)), False, 'u-interval-open-hi')
    chk(unary_test('(1000..5000]', D(1000)), False, 'u-interval-open-lo')
    chk(unary_test('1, 2, 3', D(2)), True, 'u-list')
    chk(unary_test('1, 2, 3', D(4)), False, 'u-list2')
    chk(unary_test('"差旅", "交際"', '差旅'), True, 'u-list-str')
    chk(unary_test('not(1, 2)', D(3)), True, 'u-not')
    chk(unary_test('not(1, 2)', D(1)), False, 'u-not2')
    chk(unary_test('50000', D(50000)), True, 'u-eq')
    # 安全 / 錯誤
    for bad, lbl in [('1 / 0', 'divzero'), ('foo()', 'unknownfn'),
                     ('missing', 'undefvar'), ('a.__class__', 'escape')]:
        try:
            evaluate(bad, {'a': {}})
            raise AssertionError('%s 應拋 FeelError' % lbl)
        except FeelError:
            ok += 1

    print('FEEL selftest 通過：%d 個案例' % ok)


if __name__ == '__main__':
    _selftest()
