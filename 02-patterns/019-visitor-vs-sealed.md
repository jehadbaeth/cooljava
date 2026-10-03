# 019 · The Visitor Pattern Is Dead, Long Live Sealed Types

> Double dispatch, `accept` methods and a visitor interface per tree, all to simulate a `switch` that Java can now do natively and check for completeness.

**Since:** Java 21 · **Category:** [Design Patterns, Modernized](../README.md#design-patterns-modernized) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

You have a tree of node types, say an arithmetic expression with numbers, additions and multiplications, and you want many operations over it: evaluate, pretty-print, type check, optimize. Putting every operation as a method on every node class scatters each operation across all the classes. Writing `if (e instanceof Add) ... else if (e instanceof Mul) ...` chains loses all compile-time checking: forget a case and you find out at run time.

For 25 years the Java answer was the **Visitor** pattern: every node gets an `accept(Visitor v)` method that calls back `v.visitAdd(this)`, and every operation is a class implementing one `visitX` method per node type. It works, and it is a lot of ceremony to get what other languages call pattern matching.

## The trick

Since Java 21 the language has the real thing. Make the node type a **sealed interface**, make the nodes **records**, and write each operation as a **`switch` with record patterns**:

```java
sealed interface Expr permits Num, Add, Mul {}
record Num(int value) implements Expr {}
record Add(Expr left, Expr right) implements Expr {}
record Mul(Expr left, Expr right) implements Expr {}

static int eval(Expr e) {
    return switch (e) {
        case Num(int value) -> value;
        case Add(Expr l, Expr r) -> eval(l) + eval(r);
        case Mul(Expr l, Expr r) -> eval(l) * eval(r);
    };
}
```

No `accept`, no visitor interface, no `default`. Because the hierarchy is sealed, the compiler knows that these three cases are *all* the cases. Add a fourth record and every such `switch` stops compiling until it handles the newcomer. That is exactly the safety net the visitor gave you, without the scaffolding.

## Full example

```java run
public class VisitorVsSealed {

    // The classic Visitor (Gang of Four), double dispatch through accept and visitX.
    static final class Classic {
        interface Expr { <R> R accept(Visitor<R> v); }

        interface Visitor<R> {
            R visitNum(Num n);
            R visitAdd(Add a);
            R visitMul(Mul m);
        }

        record Num(int value) implements Expr { public <R> R accept(Visitor<R> v) { return v.visitNum(this); } }
        record Add(Expr left, Expr right) implements Expr { public <R> R accept(Visitor<R> v) { return v.visitAdd(this); } }
        record Mul(Expr left, Expr right) implements Expr { public <R> R accept(Visitor<R> v) { return v.visitMul(this); } }

        static final class Eval implements Visitor<Integer> {
            public Integer visitNum(Num n) { return n.value(); }
            public Integer visitAdd(Add a) { return a.left().accept(this) + a.right().accept(this); }
            public Integer visitMul(Mul m) { return m.left().accept(this) * m.right().accept(this); }
        }

        static final class Show implements Visitor<String> {
            public String visitNum(Num n) { return Integer.toString(n.value()); }
            public String visitAdd(Add a) { return "(" + a.left().accept(this) + " + " + a.right().accept(this) + ")"; }
            public String visitMul(Mul m) { return m.left().accept(this) + " * " + m.right().accept(this); }
        }
    }

    // The modern version: a sealed interface, records and pattern matching.
    sealed interface Expr permits Num, Add, Mul {}
    record Num(int value) implements Expr {}
    record Add(Expr left, Expr right) implements Expr {}
    record Mul(Expr left, Expr right) implements Expr {}

    static int eval(Expr e) {
        return switch (e) {
            case Num(int value) -> value;
            case Add(Expr l, Expr r) -> eval(l) + eval(r);
            case Mul(Expr l, Expr r) -> eval(l) * eval(r);
        };
    }

    static String show(Expr e) {
        return switch (e) {
            case Num(int value) -> Integer.toString(value);
            case Add(Expr l, Expr r) -> "(" + show(l) + " + " + show(r) + ")";
            case Mul(Expr l, Expr r) -> show(l) + " * " + show(r);
        };
    }

    // A new operation is just a new function. Nested patterns match on shape, which a visitor cannot.
    static String lint(Expr e) {
        return switch (e) {
            case Mul(Num(int one), Expr x) when one == 1 -> "multiplying by 1 is a no-op: " + show(e);
            case Mul(Expr x, Num(int zero)) when zero == 0 -> "always zero: " + show(e);
            case Add(Expr l, Expr r) when l.equals(r) -> "could be 2 * " + show(l);
            case Num n -> "fine";
            case Add(Expr l, Expr r) -> combine(lint(l), lint(r));
            case Mul(Expr l, Expr r) -> combine(lint(l), lint(r));
        };
    }

    static String combine(String a, String b) { return a.equals("fine") ? b : a; }

    public static void main(String[] args) {
        var classic = new Classic.Mul(new Classic.Add(new Classic.Num(2), new Classic.Num(3)), new Classic.Num(4));
        System.out.println("classic: " + classic.accept(new Classic.Show()) + " = " + classic.accept(new Classic.Eval()));

        Expr modern = new Mul(new Add(new Num(2), new Num(3)), new Num(4));
        System.out.println("sealed:  " + show(modern) + " = " + eval(modern));

        for (Expr e : new Expr[] {
                modern,
                new Add(new Num(7), new Mul(new Num(1), new Num(9))),
                new Mul(new Add(new Num(1), new Num(2)), new Num(0)),
                new Add(new Mul(new Num(2), new Num(5)), new Mul(new Num(2), new Num(5)))}) {
            System.out.println("lint " + show(e) + " -> " + lint(e));
        }
    }
}
```

Output:

```text output
classic: (2 + 3) * 4 = 20
sealed:  (2 + 3) * 4 = 20
lint (2 + 3) * 4 -> fine
lint (7 + 1 * 9) -> multiplying by 1 is a no-op: 1 * 9
lint (1 + 2) * 0 -> always zero: (1 + 2) * 0
lint (2 * 5 + 2 * 5) -> could be 2 * 2 * 5
```

Now add negation. In the sealed version you add one record, and javac flags every exhaustive `switch` that has not caught up. Watch which of the two operations it flags:

```java compile-fail
public class AddNegation {
    sealed interface Expr permits Num, Add, Mul, Neg {}
    record Num(int value) implements Expr {}
    record Add(Expr left, Expr right) implements Expr {}
    record Mul(Expr left, Expr right) implements Expr {}
    record Neg(Expr inner) implements Expr {}

    static int eval(Expr e) {
        return switch (e) {
            case Num(int value) -> value;
            case Add(Expr l, Expr r) -> eval(l) + eval(r);
            case Mul(Expr l, Expr r) -> eval(l) * eval(r);
        };
    }

    static int size(Expr e) {
        return switch (e) {
            case Add(Expr l, Expr r) -> 1 + size(l) + size(r);
            case Mul(Expr l, Expr r) -> 1 + size(l) + size(r);
            default -> 1;   // "everything else is a leaf": true until Neg arrived
        };
    }

    public static void main(String[] args) {}
}
```

```text compile-error
AddNegation.java:9: error: the switch expression does not cover all possible input values
        return switch (e) {
               ^
1 error
```

The classic visitor is just as strict. Add `visitNeg` to the visitor interface and every visitor fails:

```java compile-fail
public class ClassicNegation {
    interface Expr { <R> R accept(Visitor<R> v); }
    interface Visitor<R> { R visitNum(Num n); R visitNeg(Neg n); }

    record Num(int value) implements Expr { public <R> R accept(Visitor<R> v) { return v.visitNum(this); } }
    record Neg(Expr inner) implements Expr { public <R> R accept(Visitor<R> v) { return v.visitNeg(this); } }

    static final class Eval implements Visitor<Integer> {
        public Integer visitNum(Num n) { return n.value(); }
    }

    public static void main(String[] args) {}
}
```

```text compile-error
ClassicNegation.java:8: error: Eval is not abstract and does not override abstract method visitNeg(Neg) in Visitor
    static final class Eval implements Visitor<Integer> {
                 ^
1 error
```

## How it works

* **The visitor is a hand-built `switch`.** `accept` dispatches on the node's runtime class (first dispatch), and the call `v.visitAdd(this)` picks the operation's method (second dispatch). That double dispatch exists only because Java could not `switch` on types. Pattern matching for `switch` (JEP 441) plus sealed types (JEP 409) do the same job in the language.
* **Exhaustiveness replaces the visitor interface.** In the classic version, the list of `visitX` methods *is* the list of cases, and the compiler enforces it through `implements Visitor<R>`. In the sealed version, the `permits` clause is the list, and the compiler enforces it on every `switch` without a `default`. The two compile errors above are the same safety net in two outfits.
* **Record patterns deconstruct.** `case Add(Expr l, Expr r)` checks the type *and* binds the children in one step, so there are no casts and no accessor calls.
* **Nested patterns go beyond the visitor.** `lint` matches `Mul(Num(1), x)`, a multiplication whose *left child* is the literal 1. A visitor dispatches on one level only; to express this you would need nested `instanceof` checks inside `visitMul`. Guards (`when one == 1`) refine a pattern with an arbitrary condition, and the general cases at the end catch everything the specific ones did not.
* **Order matters for overlapping patterns.** The specific `Add(...) when l.equals(r)` comes before the general `Add(Expr l, Expr r)`. The output shows it working: `(2 * 5 + 2 * 5)` is reported as `could be 2 * 2 * 5`. Swap the two `Add` cases and javac rejects the guarded one as dominated, because a pattern without a guard that comes first already matches every `Add`.
* **The `default` in `size` compiled without a word.** The error lists only `eval`. That is the most important gotcha of this whole approach.

### The expression problem, honestly

Philip Wadler named it in 1998, in a note to the Java genericity mailing list: think of node types as rows and operations as columns. Object-oriented classes make new rows easy (add a subclass) and new columns hard (touch every class). Functional data types make new columns easy (add a function) and new rows hard (touch every function).

The visitor pattern moves Java from the first camp to the second. Sealed types plus pattern matching are **in the same camp as the visitor**: adding an operation is one new function, adding a node type touches every operation. They do not solve the expression problem; they make the functional side cheap and pleasant. If you truly need both directions open, look at object algebras or the tagless final style, and expect to pay in complexity.

## Gotchas

* **A `default` branch switches exhaustiveness checking off.** `size` silently treats `Neg` as a leaf and returns wrong results. In a switch over a sealed type, list the cases instead of writing `default`, even when several share a body. If you need a catch-all, write it as a pattern that still names the type, like the general `Add(Expr l, Expr r)` and `Mul(Expr l, Expr r)` cases at the end of `lint`.
* **Separately compiled code fails at run time, not compile time.** If a library adds `Neg` and your `switch` was compiled against the old version, the `switch` throws `MatchException` when it meets a `Neg` (JLS §15.28.2). Recompile against new versions of sealed hierarchies you do not own.
* **Sealed means closed.** All permitted subclasses must live in the same module (or, without modules, the same package). If third parties must add node types, sealed types are the wrong tool, and so is the visitor.
* **The visitor is not dead in older code bases or tools.** `javax.lang.model` (`ElementVisitor`), ASM and many compiler front ends are built on visitors and will stay that way. Use them as they are; do not wrap them.

## When to use it (and when not to)

For any closed tree you own (ASTs, query plans, configuration models, protocol messages, domain events), use a sealed interface of records and switch expressions. It is shorter than the visitor, just as safe, and more expressive thanks to nested patterns and guards. Keep the visitor where an API already uses it, and when you need Java versions older than 21. Prefer ordinary virtual methods when the set of *operations* is fixed and small and new node types are the common change, which is the opposite trade-off.

## Related

* [040 · Algebraic Data Types with Sealed Interfaces and Records](../05-modern-language/040-algebraic-data-types.md)
* [041 · Pattern Matching for switch: The Complete Toolkit](../05-modern-language/041-switch-pattern-matching.md)
* [042 · Symbolic Differentiation with Record Patterns](../05-modern-language/042-record-patterns-simplifier.md), nested patterns doing real algebra
* [012 · Specification Pattern: Business Rules as Composable Predicates](012-specification-pattern.md), a sealed tree with four interpreters

## Sources

* Philip Wadler, [The Expression Problem](https://homepages.inf.ed.ac.uk/wadler/papers/expression/expression.txt) (1998)
* Brian Goetz, [Data Oriented Programming in Java](https://www.infoq.com/articles/data-oriented-programming-java/), InfoQ
* [JEP 441: Pattern Matching for switch](https://openjdk.org/jeps/441) and [JEP 409: Sealed Classes](https://openjdk.org/jeps/409)
* [JLS §15.28.2: Run-Time Evaluation of switch Expressions](https://docs.oracle.com/javase/specs/jls/se25/html/jls-15.html#jls-15.28.2)
* [Visitor pattern](https://en.wikipedia.org/wiki/Visitor_pattern), Wikipedia
