# 042 · Symbolic Differentiation with Record Patterns

> A computer algebra system in one class: five records, a sealed interface, and rewrite rules that look like the math on the whiteboard.

**Since:** Java 22 · **Category:** [Modern Language Features](../README.md#modern-language-features) · **Level:** Advanced · **Verdict:** 🧪 Party trick

## The problem

Differentiation is a set of rewrite rules on the *shape* of an expression: the derivative of a sum is the sum of the derivatives, a constant times anything keeps the constant, `u^n` becomes `n*u^(n-1)*u'`. Simplification is the same: `0*u` is `0`, `u + 0` is `u`, `c1*(c2*u)` is `(c1*c2)*u`.

Before Java 21, code that matched on shape meant a visitor, and every rule that looks one level deeper meant casts. Here is just "`0*u` is `0`" in the classic style:

```java
class Simplifier implements Visitor<Expr> {
    public Expr visitMul(Mul m) {
        Expr left = m.left().accept(this);
        Expr right = m.right().accept(this);
        if (left instanceof Const && ((Const) left).value() == 0) return new Const(0);
        if (right instanceof Const && ((Const) right).value() == 0) return new Const(0);
        // ...fifteen more rules, three more visit methods, one accept() per class
        return new Mul(left, right);
    }
}
```

The rule is buried in plumbing. It should be one line.

## The trick

**Nested record patterns** let a `case` label describe a whole subtree, bind the parts you need and ignore the rest with `_`. A guard (`when`) covers what a pattern cannot say:

```java
case Mul(Const(var zero), _) when zero == 0 -> num(0);
case Mul(Const(var a), Mul(Const(var b), var u)) -> mul(num(a * b), u);
case Add(var u, var v) when u.equals(v) -> mul(num(2), u);
```

Each rule is one line, and the nesting shows exactly how deep it looks. Records also give you structural `equals` for free, which does two jobs: `u.equals(v)` recognizes like terms, and "simplify until nothing changes" becomes `next.equals(current)`.

Java has no *constant* patterns, so `Mul(Const(0), _)` does not compile. Bind the value and test it in a guard instead, as above.

## Full example

All derivatives below are with respect to `x`. Each example prints the function, the raw derivative straight from the calculus rules, and the simplified result.

```java run
import java.util.List;

public class Calculus {

    sealed interface Expr permits Const, Var, Add, Mul, Pow {}
    record Const(long value) implements Expr {}
    record Var(String name) implements Expr {}
    record Add(Expr left, Expr right) implements Expr {}
    record Mul(Expr left, Expr right) implements Expr {}
    record Pow(Expr base, long exponent) implements Expr {
        Pow {
            if (exponent < 0) throw new IllegalArgumentException("only natural exponents: " + exponent);
        }
    }

    static Expr num(long c) { return new Const(c); }
    static Expr add(Expr a, Expr b) { return new Add(a, b); }
    static Expr mul(Expr a, Expr b) { return new Mul(a, b); }
    static Expr pow(Expr a, long n) { return new Pow(a, n); }

    // d/dx, one case per rule from calculus class.
    static Expr derive(Expr e, String x) {
        return switch (e) {
            case Const _ -> num(0);
            case Var(var name) when name.equals(x) -> num(1);
            case Var _ -> num(0);
            case Add(var u, var v) -> add(derive(u, x), derive(v, x));
            case Mul(Const c, var u) -> mul(c, derive(u, x));                       // constant factor
            case Mul(var u, var v) -> add(mul(derive(u, x), v), mul(u, derive(v, x)));  // product rule
            case Pow(_, var n) when n == 0 -> num(0);
            case Pow(var u, var n) -> mul(mul(num(n), pow(u, n - 1)), derive(u, x));  // power and chain rule
        };
    }

    // One rewrite at the root. Nested patterns say exactly which shape each rule wants.
    static Expr rewrite(Expr e) {
        return switch (e) {
            case Add(Const(var a), Const(var b)) -> num(a + b);
            case Add(Const(var zero), var u) when zero == 0 -> u;
            case Add(var u, Const(var zero)) when zero == 0 -> u;
            case Add(var u, var v) when u.equals(v) -> mul(num(2), u);
            case Add(Mul(Const(var a), var u), var v) when u.equals(v) -> mul(num(a + 1), u);
            case Add(Const c, var u) -> add(u, c);                                   // x + 2, not 2 + x
            case Mul(Const(var a), Const(var b)) -> num(a * b);
            case Mul(Const(var zero), _) when zero == 0 -> num(0);
            case Mul(_, Const(var zero)) when zero == 0 -> num(0);
            case Mul(Const(var one), var u) when one == 1 -> u;
            case Mul(var u, Const(var one)) when one == 1 -> u;
            case Mul(var u, Const c) -> mul(c, u);                                   // 2x, not x*2
            case Mul(Const(var a), Mul(Const(var b), var u)) -> mul(num(a * b), u);
            case Mul(var u, var v) when u.equals(v) -> pow(u, 2);
            case Mul(Pow(var u, var n), var v) when u.equals(v) -> pow(u, n + 1);
            case Mul(Mul(Const c, var u), var v) when u.equals(v) -> mul(c, pow(u, 2));
            case Pow(_, var n) when n == 0 -> num(1);
            case Pow(var u, var n) when n == 1 -> u;
            case Pow(Const(var c), var n) -> num(power(c, n));
            default -> e;                                                            // no rule applies
        };
    }

    // Simplify children first, then the root, until nothing changes. Record equals makes "changed?" free.
    static Expr simplify(Expr e) {
        Expr current = e;
        while (true) {
            Expr next = rewrite(switch (current) {
                case Add(var u, var v) -> add(simplify(u), simplify(v));
                case Mul(var u, var v) -> mul(simplify(u), simplify(v));
                case Pow(var u, var n) -> pow(simplify(u), n);
                case Const _, Var _ -> current;
            });
            if (next.equals(current)) return current;
            current = next;
        }
    }

    static String show(Expr e) {
        return switch (e) {
            case Const(var c) -> Long.toString(c);
            case Var(var name) -> name;
            case Add(var u, var v) -> show(u) + " + " + show(v);
            case Mul(Const(var c), var u) when u instanceof Var || u instanceof Pow(Var _, _) -> c + show(u);
            case Mul(var u, var v) -> wrap(u) + "*" + wrap(v);
            case Pow(var u, var n) -> wrap(u) + "^" + n;
        };
    }

    static String wrap(Expr e) { return e instanceof Add ? "(" + show(e) + ")" : show(e); }

    static long eval(Expr e, long x) {
        return switch (e) {
            case Const(var c) -> c;
            case Var _ -> x;
            case Add(var u, var v) -> eval(u, x) + eval(v, x);
            case Mul(var u, var v) -> eval(u, x) * eval(v, x);
            case Pow(var u, var n) -> power(eval(u, x), n);
        };
    }

    static long power(long base, long n) {
        long result = 1;
        for (long i = 0; i < n; i++) result *= base;
        return result;
    }

    public static void main(String[] args) {
        Expr x = new Var("x"), y = new Var("y");
        var examples = List.of(
                add(pow(x, 3), mul(num(2), x)),
                mul(x, x),
                mul(pow(x, 2), y),
                pow(add(mul(num(3), x), num(5)), 2),
                mul(pow(x, 2), x),
                mul(mul(x, y), x));

        boolean allAgree = true;
        for (Expr f : examples) {
            Expr raw = derive(f, "x");
            Expr clean = simplify(raw);
            System.out.println("f  = " + show(f));
            System.out.println("f' = " + show(raw));
            System.out.println("   = " + show(clean));
            for (long v = -3; v <= 3; v++) allAgree &= eval(raw, v) == eval(clean, v);
        }
        System.out.println("simplified and raw agree for x in -3..3: " + allAgree);
    }
}
```

Output:

```text output
f  = x^3 + 2x
f' = 3x^2*1 + 2*1
   = 3x^2 + 2
f  = x*x
f' = 1x + x*1
   = 2x
f  = x^2*y
f' = 2x^1*1*y + x^2*0
   = 2x*y
f  = (3x + 5)^2
f' = 2*(3x + 5)^1*(3*1 + 0)
   = 6*(3x + 5)
f  = x^2*x
f' = 2x^1*1*x + x^2*1
   = 3x^2
f  = x*y*x
f' = (1y + x*0)*x + x*y*1
   = y*x + x*y
simplified and raw agree for x in -3..3: true
```

## How it works

* **The data model is five lines.** `Expr` is a sealed sum of five records, so every `switch` over it is checked for exhaustiveness. `derive`, `show` and `eval` have no `default`: add a `Sin` record tomorrow and those three methods stop compiling until you teach them about sines.
* **`derive` reads like a textbook.** The constant factor rule `Mul(Const c, var u)` sits above the general product rule `Mul(var u, var v)`, and since `switch` tries labels top to bottom, the specific rule wins. Swap them and javac reports the constant factor case as dominated, because the general pattern already matches everything it would.
* **`rewrite` is one step at the root**, and `simplify` drives it: simplify the children, rewrite the root, repeat until a fixpoint. Rewrites enable further rewrites, so a single pass is not enough: for `(3x + 5)^2` the first round turns `2*(3x + 5)^1*(3*1 + 0)` into `3*2*(3x + 5)` (children cleaned up, then the constant moved to the front), the second folds the constants into `6*(3x + 5)`, and the third changes nothing, which ends the loop. The `equals` check costs nothing to write because records already define it structurally.
* **`default -> e` is legitimate here.** In [040](040-algebraic-data-types.md) a `default` hides missing cases. In `rewrite` it means "no rule applies, leave it alone", which is exactly the semantics we want for any shape, including future ones.
* **Patterns compose with `instanceof`.** `show` prints `3x^2` rather than `3*x^2` with the guard `u instanceof Pow(Var _, _)`, a record pattern used outside a switch.
* **`eval` is the safety net.** The last line checks that every simplified derivative agrees with its raw version for x from -3 to 3. A wrong rewrite rule almost always changes the value somewhere, so this cheap check catches most mistakes. For a real system, turn it into a property test ([026](../03-build-it-yourself/026-property-based-testing.md)).
* **The badge says 22 because of `_`.** Replace every `_` with a named binding (`Const c`, `Var v`) and the program compiles on Java 21, where record patterns became final.

## Gotchas

* **Simplification is the hard part, not differentiation.** Look at the last example: `y*x + x*y` is correct and not simplified, because the rules do not know multiplication is commutative. Fixing that properly means a canonical form (sorted factors, collected like terms, a polynomial representation). Abelson and Sussman make the same point about their Lisp version in SICP: the derivative rules are easy, deciding what "simplest" means is not.
* **Rule order is semantics.** `Add(Const c, var u) -> add(u, c)` moves constants to the right. If another rule moved them back to the left, `simplify` would loop forever. Every reordering rule needs a direction, and the set of rules needs to terminate, which no compiler checks for you.
* **`long` overflows silently.** `num(a * b)` and `power` wrap around on large constants, and `eval` agrees with itself while being wrong. Use `Math.multiplyExact` or `BigInteger` if the coefficients can grow.
* **Deep recursion.** `simplify` recurses on the tree and re-simplifies children on each round. Fine for whiteboard formulas, not for expressions with a million nodes; there you want an iterative rewriter with memoization.

## When to use it (and when not to)

Use nested record patterns whenever your logic is "if the data looks like *this*, produce *that*": compilers and interpreters, query optimizers, rule engines, JSON or AST transformations, protocol message handling. It is the feature that makes Java pleasant for writing small languages.

Do not write your own computer algebra system for production use. The 🧪 verdict is for the CAS, not for the technique: the rules here are a demo, and real systems (Symja on the JVM, or SymPy, Maxima and Mathematica elsewhere) spend decades on simplification.

## Related

* [040 · Algebraic Data Types with Sealed Interfaces and Records](040-algebraic-data-types.md)
* [041 · Pattern Matching for switch: The Complete Toolkit](041-switch-pattern-matching.md)
* [019 · The Visitor Pattern Is Dead, Long Live Sealed Types](../02-patterns/019-visitor-vs-sealed.md)
* [027 · A JSON Parser with Sealed Types](../03-build-it-yourself/027-json-parser.md)

## Sources

* Abelson and Sussman, [SICP §2.3.2: Example: Symbolic Differentiation](https://sarabander.github.io/sicp/html/2_002e3.xhtml)
* [JEP 440: Record Patterns](https://openjdk.org/jeps/440)
* [JEP 456: Unnamed Variables & Patterns](https://openjdk.org/jeps/456)
* [Expression problem](https://en.wikipedia.org/wiki/Expression_problem), Wikipedia, on why sealed types and visitors trade off differently
