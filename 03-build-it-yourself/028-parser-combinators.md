# 028 · Parser Combinators: Grammars as Code

> A parser is just a function from input to a result. Give it `then`, `or` and `many`, and the grammar stops being control flow buried in methods and becomes a value you can read, pass around and reuse.

**Since:** Java 21 · **Category:** [Build It Yourself](../README.md#build-it-yourself) · **Level:** Intermediate · **Verdict:** ⚠️ Situational

## The problem

The [JSON parser](027-json-parser.md) is hand-written recursive descent: one method per grammar rule, a cursor, and `if` statements that peek at the next character. It works, and for a small fixed format it is hard to beat. But the grammar itself is not visible anywhere. It is spread over control flow, and the cleverness lives in details like "loop here, recurse there".

Arithmetic shows how fragile that gets. Precedence (`*` binds tighter than `+`), associativity (`10 - 3 - 2` is `5`, not `9`) and unary minus all have to be encoded by hand in the order of calls and the shape of loops. The classic slip is to write `expr = term ('-' expr)?` because it recurses so nicely. It parses, and it quietly evaluates `10 - 3 - 2` as `10 - (3 - 2)`.

## The trick

Model a parser as a function `(input, position) -> Result`, where a result is either success (the value and the next position) or failure (a position and what was expected). That is all a parser is. Then write small functions that take parsers and return bigger parsers. These are the **combinators**, and each one mirrors a piece of grammar notation:

| Combinator | Grammar | Meaning |
|---|---|---|
| `string("+")`, `satisfy(test, what)` | literal, character class | consume matching input |
| `a.then(b, f)`, `skipThen`, `thenSkip` | `a b` | sequence, combining or keeping one side |
| `a.or(b)` | `a \| b` | ordered choice |
| `a.many()`, `a.some()`, `a.optional()` | `a*`, `a+`, `a?` | repetition |
| `a.sepBy(sep)` | `[a (sep a)*]` | lists |
| `a.map(f)` | semantic action | build values from matches |
| `lazy(() -> p)` | rule reference | recursion (a grammar refers to itself) |
| `chainLeft(operand, op)` | `operand (op operand)*` | binary operators, folded to the left |

The idea comes from functional programming: Graham Hutton and Erik Meijer described monadic parser combinators in the 1990s, and Daan Leijen's Parsec made the style practical. In Java it needs only a functional interface, records and a `switch`.

With them, the grammar for the evaluator below is five lines, and the code that implements it has the same shape:

```text
expr  = term  (('+' | '-') term)*
term  = unary (('*' | '/') unary)*
unary = '-' unary | power
power = atom ('^' unary)?
atom  = number | name '(' [expr (',' expr)*] ')' | '(' expr ')'
```

Precedence is the layering: each rule's operands are the next tighter rule, so `*` is parsed deeper in the tree than `+`. Left associativity is a loop folded from the left (`chainLeft`). Right associativity, needed for `^`, is recursion on the right.

## Full example

The first half is a complete combinator library (about 110 lines). The second half is the arithmetic grammar, a sealed `Expr` tree with a `switch` evaluator and printer, and a demo that prints the tree shape, the result, and what happens on bad input.

```java run
import java.util.*;
import java.util.function.*;
import java.util.stream.Collectors;

public class ParserDemo {

    // ---------- The core: a parser is a function from (input, position) to a Result ----------

    sealed interface Result<T> {}
    record Ok<T>(T value, int next) implements Result<T> {}
    record Fail<T>(int pos, String expected) implements Result<T> {
        <R> Fail<R> as() { return new Fail<>(pos, expected); }
    }

    @FunctionalInterface
    interface Parser<T> {
        Result<T> parse(String in, int pos);

        default <R> Parser<R> map(Function<? super T, ? extends R> f) {
            return (in, pos) -> switch (parse(in, pos)) {
                case Ok<T>(var value, var next) -> new Ok<>(f.apply(value), next);
                case Fail<T> fail -> fail.as();
            };
        }

        default <U, R> Parser<R> then(Parser<U> next, BiFunction<? super T, ? super U, ? extends R> combine) {
            return (in, pos) -> switch (parse(in, pos)) {
                case Ok<T>(var a, var mid) -> switch (next.parse(in, mid)) {
                    case Ok<U>(var b, var end) -> new Ok<>(combine.apply(a, b), end);
                    case Fail<U> fail -> fail.as();
                };
                case Fail<T> fail -> fail.as();
            };
        }

        default <U> Parser<U> skipThen(Parser<U> next) { return then(next, (a, b) -> b); }
        default <U> Parser<T> thenSkip(Parser<U> next) { return then(next, (a, b) -> a); }

        // Ordered choice. A failure after input was consumed is final (as in Parsec): only a clean miss falls through.
        default Parser<T> or(Parser<T> other) {
            return (in, pos) -> switch (parse(in, pos)) {
                case Ok<T> ok -> ok;
                case Fail<T> fail -> fail.pos() > pos ? fail : other.parse(in, pos);
            };
        }

        // Zero or more. Stops at a clean miss, but reports a failure that got past the starting point.
        default Parser<List<T>> many() {
            return (in, pos) -> {
                var items = new ArrayList<T>();
                int at = pos;
                while (true) {
                    switch (parse(in, at)) {
                        case Ok<T>(var value, var next) -> {
                            if (next == at) return new Ok<>(items, at);          // no progress: stop instead of looping forever
                            items.add(value);
                            at = next;
                        }
                        case Fail<T> fail -> { return fail.pos() > at ? fail.as() : new Ok<>(items, at); }
                    }
                }
            };
        }

        default Parser<List<T>> some() { return then(many(), ParserDemo::cons); }
        default Parser<List<T>> sepBy(Parser<?> separator) {
            return then(separator.skipThen(this).many(), ParserDemo::cons).or(succeed(List.of()));
        }
        default Parser<Optional<T>> optional() { return map(Optional::of).or(succeed(Optional.empty())); }

        // Name a whole group: a clean miss reports "operand" instead of whatever the last alternative expected.
        default Parser<T> label(String name) {
            return (in, pos) -> switch (parse(in, pos)) {
                case Fail<T> fail when fail.pos() == pos -> new Fail<>(pos, name);
                case Result<T> other -> other;
            };
        }
    }

    static <T> List<T> cons(T head, List<T> tail) {
        var all = new ArrayList<T>(tail.size() + 1);
        all.add(head);
        all.addAll(tail);
        return all;
    }

    static <T> Parser<T> succeed(T value) { return (in, pos) -> new Ok<>(value, pos); }

    static Parser<String> string(String s) {
        return (in, pos) -> in.startsWith(s, pos) ? new Ok<>(s, pos + s.length()) : new Fail<>(pos, "'" + s + "'");
    }

    static Parser<Character> satisfy(Predicate<Character> test, String what) {
        return (in, pos) -> pos < in.length() && test.test(in.charAt(pos))
                ? new Ok<>(in.charAt(pos), pos + 1) : new Fail<>(pos, what);
    }

    static Parser<Void> eof() {
        return (in, pos) -> pos == in.length() ? new Ok<>(null, pos) : new Fail<>(pos, "end of input");
    }

    // Grammars are recursive, parsers are built eagerly: lazy() breaks the cycle by looking the target up at parse time.
    static <T> Parser<T> lazy(Supplier<Parser<T>> target) { return (in, pos) -> target.get().parse(in, pos); }

    record Step<T>(BinaryOperator<T> op, T right) {}

    // operand (op operand)*, folded to the LEFT: 10 - 3 - 2 is (10 - 3) - 2
    static <T> Parser<T> chainLeft(Parser<T> operand, Parser<BinaryOperator<T>> op) {
        return operand.then(op.then(operand, Step::new).many(), (first, steps) -> {
            T acc = first;
            for (Step<T> step : steps) acc = step.op().apply(acc, step.right());
            return acc;
        });
    }

    // ---------- The grammar ----------
    //   expr  = term  (('+' | '-') term)*
    //   term  = unary (('*' | '/') unary)*
    //   unary = '-' unary | power
    //   power = atom ('^' unary)?
    //   atom  = number | name '(' [expr (',' expr)*] ')' | '(' expr ')'

    sealed interface Expr {}
    record Num(double value) implements Expr {}
    record Neg(Expr operand) implements Expr {}
    record Bin(char op, Expr left, Expr right) implements Expr {}
    record Call(String name, List<Expr> args) implements Expr {}

    static final Parser<Void> SPACES = satisfy(Character::isWhitespace, "whitespace").many().map(x -> null);

    static <T> Parser<T> token(Parser<T> p) { return p.thenSkip(SPACES); }          // every token eats trailing spaces
    static Parser<String> symbol(String s) { return token(string(s)); }
    static Parser<BinaryOperator<Expr>> binary(char c) { return symbol("" + c).map(x -> (l, r) -> new Bin(c, l, r)); }

    static String text(List<Character> chars) { return chars.stream().map(String::valueOf).collect(Collectors.joining()); }

    static final Parser<String> DIGITS = satisfy(Character::isDigit, "digit").some().map(ParserDemo::text);
    static final Parser<String> NAME = satisfy(Character::isLetter, "name").some().map(ParserDemo::text);

    static final Parser<Expr> NUMBER = token(DIGITS
            .then(string(".").skipThen(DIGITS).optional(), (whole, frac) -> whole + frac.map(f -> "." + f).orElse(""))
            .map(s -> new Num(Double.parseDouble(s))));

    // Inside a field initializer, the recursive reference must be qualified (see the compile-fail example below).
    static final Parser<Expr> CALL = token(NAME).then(
            symbol("(").skipThen(lazy(() -> ParserDemo.EXPR).sepBy(symbol(","))).thenSkip(symbol(")")), Call::new);
    static final Parser<Expr> PARENS = symbol("(").skipThen(lazy(() -> ParserDemo.EXPR)).thenSkip(symbol(")"));
    static final Parser<Expr> ATOM = NUMBER.or(CALL).or(PARENS).label("operand");

    static final Parser<Expr> POWER = ATOM.then(symbol("^").skipThen(lazy(() -> ParserDemo.UNARY)).optional(),
            (base, exponent) -> exponent.<Expr>map(e -> new Bin('^', base, e)).orElse(base));   // right recursion: 2^3^2 is 2^(3^2)
    static final Parser<Expr> UNARY = symbol("-").skipThen(lazy(() -> ParserDemo.UNARY)).<Expr>map(Neg::new).or(POWER);
    static final Parser<Expr> TERM = chainLeft(UNARY, binary('*').or(binary('/')));
    static final Parser<Expr> EXPR = chainLeft(TERM, binary('+').or(binary('-')));
    static final Parser<Expr> PROGRAM = SPACES.skipThen(EXPR).thenSkip(eof());

    // ---------- Evaluate and print the tree ----------

    static double eval(Expr expr) {
        return switch (expr) {
            case Num(var value) -> value;
            case Neg(var operand) -> -eval(operand);
            case Bin(var op, var left, var right) -> switch (op) {
                case '+' -> eval(left) + eval(right);
                case '-' -> eval(left) - eval(right);
                case '*' -> eval(left) * eval(right);
                case '/' -> eval(left) / eval(right);
                default -> Math.pow(eval(left), eval(right));
            };
            case Call(var name, var args) -> {
                double[] values = args.stream().mapToDouble(ParserDemo::eval).toArray();
                yield switch (name) {
                    case "max" -> Arrays.stream(values).max().orElse(Double.NaN);
                    case "sum" -> Arrays.stream(values).sum();
                    default -> throw new IllegalArgumentException("unknown function " + name);
                };
            }
        };
    }

    static String show(Expr expr) {                      // fully parenthesized: the tree shape made visible
        return switch (expr) {
            case Num(var value) -> number(value);
            case Neg(var operand) -> "(-" + show(operand) + ")";
            case Bin(var op, var left, var right) -> "(" + show(left) + " " + op + " " + show(right) + ")";
            case Call(var name, var args) -> name + args.stream().map(ParserDemo::show).collect(Collectors.joining(", ", "(", ")"));
        };
    }

    static String number(double d) { return d == Math.rint(d) ? String.valueOf((long) d) : String.valueOf(d); }

    static void run(String input) {
        var label = "\"" + input + "\"";
        switch (PROGRAM.parse(input, 0)) {
            case Ok<Expr>(var expr, var end) -> System.out.printf("%-22s %-28s = %s%n", label, show(expr), number(eval(expr)));
            case Fail<Expr>(var pos, var expected) -> System.out.printf("%-22s error at %d: expected %s%n", label, pos, expected);
        }
    }

    public static void main(String[] args) {
        System.out.println("precedence and associativity:");
        for (String input : List.of("2 + 3 * 4", "(2 + 3) * 4", "10 - 3 - 2", "8 / 4 / 2", "2 ^ 3 ^ 2", "-2 ^ 2", "2 ^ -1",
                "  1.5 * 4 - -2 ", "max(1, 2 + 3, 4) * 2", "sum() + 1")) {
            run(input);
        }

        System.out.println("errors carry the position:");
        for (String input : List.of("1 +", "2 * (3 + 4", "7 $ 2", "max(1,)", "1.")) {
            run(input);
        }

        System.out.println("recursion limits:");
        try {
            LEFT_RECURSIVE.parse("1 - 2", 0);
        } catch (StackOverflowError e) {
            System.out.println("  left recursive grammar: StackOverflowError");
        }
        for (int depth : new int[] {100, 100_000}) {
            String nested = "(".repeat(depth) + "1" + ")".repeat(depth);
            try {
                PROGRAM.parse(nested, 0);
                System.out.println("  " + depth + " nested parentheses: parsed");
            } catch (StackOverflowError e) {
                System.out.println("  " + depth + " nested parentheses: StackOverflowError");
            }
        }
    }

    // expr = expr '-' number | number: the first thing this parser does is call itself
    static final Parser<Expr> LEFT_RECURSIVE = lazy(() -> ParserDemo.LEFT_RECURSIVE)
            .then(symbol("-").skipThen(NUMBER), (l, r) -> (Expr) new Bin('-', l, r)).or(NUMBER);
}
```

Output:

```text output
precedence and associativity:
"2 + 3 * 4"            (2 + (3 * 4))                = 14
"(2 + 3) * 4"          ((2 + 3) * 4)                = 20
"10 - 3 - 2"           ((10 - 3) - 2)               = 5
"8 / 4 / 2"            ((8 / 4) / 2)                = 1
"2 ^ 3 ^ 2"            (2 ^ (3 ^ 2))                = 512
"-2 ^ 2"               (-(2 ^ 2))                   = -4
"2 ^ -1"               (2 ^ (-1))                   = 0.5
"  1.5 * 4 - -2 "      ((1.5 * 4) - (-2))           = 8
"max(1, 2 + 3, 4) * 2" (max(1, (2 + 3), 4) * 2)     = 10
"sum() + 1"            (sum() + 1)                  = 1
errors carry the position:
"1 +"                  error at 3: expected operand
"2 * (3 + 4"           error at 10: expected ')'
"7 $ 2"                error at 2: expected end of input
"max(1,)"              error at 6: expected operand
"1."                   error at 2: expected digit
recursion limits:
  left recursive grammar: StackOverflowError
  100 nested parentheses: parsed
  100000 nested parentheses: StackOverflowError
```

Inside a `static final` field the recursive reference has to be written `ParserDemo.EXPR`, not `EXPR`. With the simple name javac refuses:

```java compile-fail
import java.util.function.Supplier;

public class SelfReference {
    interface Parser<T> { T parse(String in); }

    static <T> Parser<T> lazy(Supplier<Parser<T>> supplier) {
        return in -> supplier.get().parse(in);
    }

    static final Parser<String> NESTED = lazy(() -> NESTED);

    public static void main(String[] args) {}
}
```

```text compile-error
SelfReference.java:10: error: self-reference in initializer
    static final Parser<String> NESTED = lazy(() -> NESTED);
                                                    ^
1 error
```

## How it works

* **A parser is a value, built once.** Every `static final Parser<Expr>` above is a small immutable function object, assembled when the class initializes. Parsing threads an `int` position through the calls and mutates no shared state, so parsers are stateless and freely shareable between threads.
* **Precedence comes from layering.** The first output lines show it: `2 + 3 * 4` prints as `(2 + (3 * 4))` because `TERM` is the operand of `EXPR`, so a product is always finished before the sum looks at it. Parentheses restart the climb through `PARENS`, which gives `((2 + 3) * 4)`. Unary minus sits below `*` and above `^`, so `-2 ^ 2` is `(-(2 ^ 2))` and prints `-4`, the way mathematicians read it.
* **Left or right is a choice of shape.** `chainLeft` collects `(op, operand)` steps and folds them from the left, which is why `10 - 3 - 2` is `((10 - 3) - 2)` and `8 / 4 / 2` is `((8 / 4) / 2)`. `POWER` recurses into `UNARY` on its right side instead, so `2 ^ 3 ^ 2` is `(2 ^ (3 ^ 2))`, which is `512`, not `64`. The same recursion lets `2 ^ -1` work, because the exponent is a `UNARY`.
* **Left recursion is the one thing you cannot write.** The grammar `expr = expr '-' number | number` is the natural way to say "subtraction is left associative", but the first thing that parser does is call itself at the same position. The demo shows the result: `StackOverflowError`. The loop inside `chainLeft` is the standard cure.
* **Errors come from two rules.** `or` only tries its second alternative after a *clean miss*, meaning a failure that consumed nothing. `many` does the same: it stops quietly at a clean miss, but a failure that got past its starting point is final. That is how `1 +` reports `error at 3: expected operand` instead of quietly accepting `1` and complaining about leftover input at position 2, and how `max(1,)` points at the closing parenthesis, the place where an operand was missing. This `or` does not merge the expectations of its alternatives, it just returns the failure of the last one tried. Without help, `1 +` would report `expected '('`, because the parenthesized alternative is tried last. `label("operand")` replaces that message with a name for the whole group. Parsec follows the same consumed-input rule, which is a large part of why its errors are decent.
* **`sepBy` and `optional` are built from those pieces.** `sepBy` is `first (separator first)*` or an empty list, `optional` is `p` or `succeed(empty)`. Neither needs any new machinery, which is the point of the style: the library is tiny because every combinator is a few lines over the same `Result`.
* **Compared with [027](027-json-parser.md).** The recursive descent parser spends its code on mechanics (cursor, peeking, error messages). Here the mechanics are written once, in the combinators, and the grammar is the code. In return, a hand-written parser makes good error messages easier, allocates less, and gives readable stack traces. A failure inside this parser shows a pile of anonymous lambda frames that say little about which rule you were in. 027 also guards nesting depth (`MAX_DEPTH = 64`), and this version does not, as the last demo lines show.

## Gotchas

* **Self-reference in field initializers.** The compile-fail example above is the usual stumbling block. Qualify the reference (`ParserDemo.EXPR`), and keep the fields in dependency order, because a plain forward reference is also a compile error. If you build the grammar in `static` methods instead of fields, `lazy` is still needed at the recursion points, or construction never ends.
* **Ordered choice is not longest match.** `string("let").or(string("letter"))` succeeds on `"letter"` after consuming three characters and leaves `ter` behind. Put longer alternatives first. Parsec solves the related problem of alternatives with a shared prefix with `try`, which turns a consuming failure back into a clean miss. A parser that backtracks on every failure avoids the problem but can go exponential when alternatives share long prefixes and are nested. `(atom '^' unary) or atom` reparses `atom` at every level of nesting, which doubles the work with each parenthesis. That is the same disease as the regex blowup in [029](029-regex-engine.md), and the same cure applies (remember results by position, known as packrat parsing).
* **Whitespace is your job.** There is no lexer. Here every token (`symbol`, numbers, names) eats the whitespace after it, and `PROGRAM` skips leading whitespace once. Forget it in one place and `1 + 2` parses while `1 +2` does not.
* **The error is only as good as your labels.** `7 $ 2` reports `error at 2: expected end of input`, when the helpful message would be "expected an operator". Real libraries merge the expectations of every alternative tried at the farthest position. Here only `ATOM` has a label.
* **Recursion depth is attacker controlled.** `(` repeated 100 000 times blows the stack in this parser, as the last line of the demo shows (the exact depth where it fails depends on your stack size, so the demo uses a value far above what the default stack size allows). A formula field that accepts user input needs a depth counter, or a trampoline as in [007](../01-functional/007-trampolines.md).
* **Type inference needs help.** `symbol("-").skipThen(...).<Expr>map(Neg::new)` carries an explicit type argument because `map` alone would infer `Parser<Neg>`, and `or` wants `Parser<Expr>`. Typed fields (`static final Parser<Expr>`) fix most of it.
* **Numbers are `double`.** Division by zero gives `Infinity`, and `0.1 + 0.2` is not `0.3`. That is the evaluator's choice and has nothing to do with the parser.

## When to use it (and when not to)

Combinators shine for small, changing languages that live inside an application: filter expressions, formula fields, query strings, configuration formats, test data builders. The grammar reads like the spec, pieces like `sepBy` and `chainLeft` are reused across grammars, and the AST/evaluator split gives you a safe interpreter (a closed `switch` over records can do nothing but arithmetic, unlike evaluating user input as code, see [090](../10-jvm-performance/090-runtime-compilation-jshell.md)).

Be honest about the limits. For a fixed format with a few rules, hand-written recursive descent such as [027](027-json-parser.md) is just as short and easier to debug. Javac's own parser is hand-written Java, not generated from a grammar file (`JavacParser.java`, about 5,700 lines in JDK 25). For a real language, or a format with serious tooling needs (syntax highlighting, error recovery, several target languages), use a parser generator. [ANTLR](https://www.antlr.org/) and [JavaCC](https://javacc.github.io/javacc/) take a grammar file and generate the parser. For combinators in a library, [jparsec](https://github.com/jparsec/jparsec) exists, and its README now recommends Google's Dot Parse from the Mug library for projects on Java 21 or later. For JSON, XML or CSV, do not write a parser at all: use a library. This one allocates a `Result` per step and caches nothing, and the numbers above are about correctness, not speed. Measure before putting it on a hot path.

## Related

* [027 · A JSON Parser with Sealed Types](027-json-parser.md), the hand-written recursive descent version of the same job
* [029 · A Regex Engine in 30 Lines](029-regex-engine.md), another small notation turned into a program, and the home of backtracking blowups
* [007 · Trampolines: Stack-Safe Recursion](../01-functional/007-trampolines.md), the cure for parser recursion that follows the input depth
* [040 · Algebraic Data Types with Sealed Interfaces and Records](../05-modern-language/040-algebraic-data-types.md), the `Result` and `Expr` types used here

## Sources

* Graham Hutton and Erik Meijer, [Monadic Parser Combinators](https://www.cs.nott.ac.uk/~pszgmh/monparsing.pdf) (technical report NOTTCS-TR-96-4, 1996) and the shorter functional pearl [Monadic Parsing in Haskell](https://www.cs.nott.ac.uk/~pszgmh/pearl.pdf) (Journal of Functional Programming, 1998)
* [Parsec](https://hackage.haskell.org/package/parsec), the Haskell parser combinator library by Daan Leijen and others
* [jparsec](https://github.com/jparsec/jparsec), a parser combinator library for Java
* [JLS §8.3.3: Forward References During Field Initialization](https://docs.oracle.com/javase/specs/jls/se25/html/jls-8.html#jls-8.3.3)
