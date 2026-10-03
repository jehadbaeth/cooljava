# 051 · Weird but Legal Java Syntax

> A URL pasted into a method body compiles, `this` can be a parameter, and `i = i++` quietly does nothing. The grammar has thirty years of sediment in it, and every odd corner below is confirmed by the compiler.

**Since:** Java 8 · **Category:** [Hidden Corners and Party Tricks](../README.md#hidden-corners-and-party-tricks) · **Level:** Intermediate · **Verdict:** 🧪 Party trick

Most of this is as old as Java 1.0. The badge says 8 because receiver parameters arrived in Java 8 and the example uses one.

## The problem

Java reads like a tame language, so it is easy to believe that anything which looks wrong will not compile, and anything which compiles must do what it looks like. Neither is true. Try these before reading on:

* Does `https://example.com` compile as a statement in a method body?
* What type is `b` in `int[] a, b[];`?
* What does `i = i++;` leave in `i`?
* Is `void greet(WeirdLegalSyntax this, String who)` a method with two parameters or one?
* What is `p+++q`, and what does a `while (n --> 0)` loop do?

## The trick

There is no single trick, just a tour of corners where the grammar does something you would not guess. Each row below is exercised in the program that follows.

| Syntax | What it really is |
|---|---|
| `https://example.com` | the label `https:` followed by a `//` line comment |
| `int[] a, b[];` | `a` is `int[]`, `b` is `int[][]`: brackets on a declarator add a dimension |
| `static int digits()[]` | a method that returns `int[]`, brackets after the parameter list |
| `void greet(WeirdLegalSyntax this, String who)` | a receiver parameter: not a parameter, only a place to hang annotations |
| `outer.new Inner()` | creates an inner instance bound to a given outer instance |
| `Outer.this` | the enclosing instance, even when `this.name` shadows it |
| `outer.super();` | a constructor call that supplies the enclosing instance of the superclass |
| `i = i++;` | assigns the old value of `i` back to `i` |
| `p+++q` | tokenized greedily as `p++ + q` |
| `n --> 0` | not an operator, just `n-- > 0` |
| `'a' + 1` | `int` arithmetic: `char` is promoted |
| `;;;` | three empty statements |
| `$`, `€`, `π`, `変数` | all valid identifiers |

## Full example

Everything in the table, one section per line of output. The identifier section at the end also prints the binary name of a class called `$`, and asks the JDK whether an infinity sign may start an identifier.

```java run
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;
import java.lang.reflect.Method;
import java.util.Arrays;

public class WeirdLegalSyntax {

    @Retention(RetentionPolicy.RUNTIME)
    @Target(ElementType.TYPE_USE)
    @interface Receiver {}

    // Array brackets may follow the parameter list of a method.
    static int digits()[] { return new int[] {4, 2}; }
    static int[] rows()[] { return new int[][] {{1}, {2, 3}}; }

    // The receiver parameter: the instance written as a parameter named "this".
    void greet(@Receiver WeirdLegalSyntax this, String who) {
        System.out.println("  hello, " + who);
    }

    static class Outer {
        final String name;
        Outer(String name) { this.name = name; }

        class Inner {
            final String name = "inner";
            Inner(Outer Outer.this) {}      // a receiver parameter on an inner class constructor
            String describe() { return name + " of " + Outer.this.name; }
        }
    }

    // A subclass of an inner class must say which outer instance the superclass belongs to.
    static class Stranger extends Outer.Inner {
        Stranger(Outer outer) { outer.super(); }
    }

    static class $ {}

    public static void main(String[] args) throws Exception {
        System.out.println("1. a URL in code");
        https://example.com/docs?page=1
        for (int step = 0; step < 3; step++) {
            if (step == 1) break https;
            System.out.println("  step " + step);
        }

        System.out.println("2. mixed array declarators");
        int[] a = {1, 2}, b[] = {{3}, {4, 5}};
        System.out.println("  a is " + a.getClass().getSimpleName() + ", b is " + b.getClass().getSimpleName());
        float[][] f[][] = new float[1][1][1][1], g[][][] = new float[1][1][1][1][1], h[] = new float[1][1][1]; // Yechh!
        System.out.println("  f, g, h are " + f.getClass().getSimpleName() + ", " + g.getClass().getSimpleName()
                + ", " + h.getClass().getSimpleName());
        System.out.println("  digits() = " + Arrays.toString(digits()) + ", rows() = " + Arrays.deepToString(rows()));

        System.out.println("3. receiver parameter");
        new WeirdLegalSyntax().greet("Ada");
        Method greet = WeirdLegalSyntax.class.getDeclaredMethod("greet", String.class);
        System.out.println("  parameter count: " + greet.getParameterCount());
        System.out.println("  annotation on the receiver: "
                + greet.getAnnotatedReceiverType().getAnnotations()[0].annotationType().getSimpleName());

        System.out.println("4. inner class plumbing");
        Outer outer = new Outer("alpha");
        Outer.Inner inner = outer.new Inner();
        System.out.println("  " + inner.describe());
        System.out.println("  " + new Stranger(new Outer("beta")).describe());

        System.out.println("5. increment puzzles");
        int i = 5;
        i = i++;
        System.out.println("  i = i++ leaves " + i);
        int p = 5, q = 2;
        int r = p+++q;
        System.out.println("  p+++q is " + r + ", p is now " + p);
        StringBuilder countdown = new StringBuilder();
        int n = 3;
        while (n --> 0) countdown.append(n).append(' ');
        System.out.println("  n --> 0 prints " + countdown.toString().trim());

        System.out.println("6. char arithmetic");
        char c = 'a';
        int plain = c + 1;
        char next = (char) (c + 1);
        String left = 'a' + 'b' + "c";
        String right = "c" + 'a' + 'b';
        c += 1;
        char folded = 'a' + 1;
        System.out.println("  c + 1 = " + plain + ", (char) (c + 1) = " + next);
        System.out.println("  'a' + 'b' + \"c\" = " + left + ", \"c\" + 'a' + 'b' = " + right);
        System.out.println("  after c += 1: " + c + ", char folded = 'a' + 1: " + folded);

        System.out.println("7. empty statements");
        ;;;
        int afterFor = 0, afterIf = 0, afterWhile = 0;
        for (int k = 0; k < 3; k++);
        { afterFor++; }
        boolean enabled = false;
        if (enabled);
        { afterIf++; }
        int w = 0;
        while (w++ < 3);
        { afterWhile++; }
        System.out.println("  blocks that ran after for (...); " + afterFor + ", if (enabled); " + afterIf
                + ", while (...); " + afterWhile);

        System.out.println("8. identifiers");
        int $ = 1, € = 20, π = 300, 変数 = 4000;
        System.out.println("  sum = " + ($ + € + π + 変数));
        System.out.println("  class $ has the binary name " + $.class.getName());
        System.out.println("  may U+20AC start an identifier: " + Character.isJavaIdentifierStart('€'));
        System.out.println("  may U+221E start an identifier: " + Character.isJavaIdentifierStart('∞'));
    }
}
```

Output:

```text output
1. a URL in code
  step 0
2. mixed array declarators
  a is int[], b is int[][]
  f, g, h are float[][][][], float[][][][][], float[][][]
  digits() = [4, 2], rows() = [[1], [2, 3]]
3. receiver parameter
  hello, Ada
  parameter count: 1
  annotation on the receiver: Receiver
4. inner class plumbing
  inner of alpha
  inner of beta
5. increment puzzles
  i = i++ leaves 5
  p+++q is 7, p is now 6
  n --> 0 prints 2 1 0
6. char arithmetic
  c + 1 = 98, (char) (c + 1) = b
  'a' + 'b' + "c" = 195c, "c" + 'a' + 'b' = cab
  after c += 1: b, char folded = 'a' + 1: b
7. empty statements
  blocks that ran after for (...); 1, if (enabled); 1, while (...); 1
8. identifiers
  sum = 4321
  class $ has the binary name WeirdLegalSyntax$$
  may U+20AC start an identifier: true
  may U+221E start an identifier: false
```

## Where the weirdness stops

Each of these is rejected, and the messages tell you which rule you hit. First the lexical and grammatical ones. A URL is only a statement inside a method body, an infinity sign is not a letter, and `var` is not allowed as a class name:

```java compile-fail
public class Rejected {
    https://example.com
    class var {}
    class _ {}
    int ∞ = 1;
}
```

```text compile-error
Rejected.java:2: error: <identifier> expected
    https://example.com
         ^
Rejected.java:3: error: 'var' not allowed here
    class var {}
          ^
  as of release 10, 'var' is a restricted type name and cannot be used for type declarations
Rejected.java:4: error: underscore not allowed here
    class _ {}
          ^
Rejected.java:5: error: illegal character: '\u221e'
    int ∞ = 1;
        ^
4 errors
```

The lone underscore is the odd one out. Since Java 9 it was a keyword and could not be an identifier at all. JEP 456 gave it a second life in Java 22 as the name of an unnamed variable, which you can declare but never read. Line 3 below is accepted by javac 25, and only the read on line 4 is an error:

```java compile-fail
public class Underscore {
    public static void main(String[] args) {
        int _ = 1;
        System.out.println(_);
    }
}
```

```text compile-error
Underscore.java:4: error: underscore not allowed here
        System.out.println(_);
                           ^
1 error
```

Then the type rules. A receiver parameter must name the class that declares the method and cannot appear on a static method, `c + 1` is an `int`, and `b` really is two dimensions deep:

```java compile-fail
public class Mismatch {
    void wrong(String this) {}
    static void alsoWrong(Mismatch this) {}

    class Inner {
        void m(Mismatch this) {}
    }

    public static void main(String[] args) {
        char c = 'a';
        c = c + 1;
        int[] a = {1}, b[] = {{2}};
        a = b;
    }
}
```

```text compile-error
Mismatch.java:2: error: the receiver type does not match the enclosing class type
    void wrong(String this) {}
               ^
  required: Mismatch
  found:    String
Mismatch.java:3: error: non-static variable this cannot be referenced from a static context
    static void alsoWrong(Mismatch this) {}
                                   ^
Mismatch.java:6: error: the receiver type does not match the enclosing class type
        void m(Mismatch this) {}
               ^
  required: Mismatch.Inner
  found:    Mismatch
Mismatch.java:11: error: incompatible types: possible lossy conversion from int to char
        c = c + 1;
              ^
Mismatch.java:13: error: incompatible types: int[][] cannot be converted to int[]
        a = b;
            ^
5 errors
```

Finally, empty statements are free, with one exception. They count as statements for reachability, so a stray semicolon after a `return` is an error, and so is the empty body of `while (false)`:

```java compile-fail
public class Unreachable {
    static int one() {
        return 1;
        ;
    }

    static void never() {
        while (false);
    }

    public static void main(String[] args) {
        System.out.println(one());
    }
}
```

```text compile-error
Unreachable.java:4: error: unreachable statement
        ;
        ^
Unreachable.java:8: error: unreachable statement
        while (false);
                     ^
2 errors
```

## How it works

* **Labels make URLs legal.** The lexer sees the identifier `https`, a colon, and then `//` starts a line comment that swallows the rest of the line. A label is a legal prefix for any statement (see [049](049-labeled-blocks.md)), and the example proves it by running `break https;`. Put the same text in a field position and it is just garbage, as the first compile-fail block shows.
* **Declarators carry their own brackets.** JLS 10.2 says brackets in declarators are "a nod to the tradition of C and C++", and that `int a, b[], c[][];` equals `int a; int[] b; int[][] c;`. The extreme example in the spec is `float[][] f[][], g[][][], h[];`, commented "Yechh!", and the program above declares it too. The method form (`int digits()[]`) is described in JLS 8.4 as supported "for compatibility with early versions", with the advice that "it is very strongly recommended that this syntax is not used in new code".
* **The receiver parameter exists for annotations.** JLS 8.4 describes it as a syntactic device with "no effect whatsoever at run time". It is not a variable, which is why `getParameterCount()` prints 1 and the callers pass one argument. It is the only way to write a type annotation on the type of `this`, and reflection can read it back through `getAnnotatedReceiverType()`. The program also gives the `Inner` constructor one, written `Outer Outer.this`, and `new Inner()` still takes no arguments.
* **`outer.new Inner()` and `outer.super()` supply the enclosing instance explicitly.** Normally `new Inner()` uses `this` as the outer instance. From the outside, or in a subclass that is not itself an inner class of `Outer`, you must name it, which is what `outer.super()` does in the constructor of `Stranger`.
* **`i = i++` is a read followed by a write of the same value.** The right side evaluates `i++`, which yields the old value 5 and increments `i` to 6, and then the assignment stores 5 over it. The output shows 5.
* **The lexer is greedy.** JLS 3.2 says "the longest possible translation is used at each step". So `p+++q` becomes `p++`, `+`, `q`, giving 5 + 2 = 7 and leaving `p` at 6. `n --> 0` is the tokens `n`, `--`, `>`, `0`.
* **`char` is a number.** Arithmetic promotes it to `int`, so `c + 1` is 98 and `'a' + 'b'` is 195 before string concatenation starts. Concatenation then goes left to right, which is why the two string results differ. Compound assignment inserts a hidden narrowing cast, so `c += 1` compiles where `c = c + 1` does not, and a constant expression that fits, like `'a' + 1`, may initialize a `char` directly.
* **Identifiers are Unicode "Java letters".** JLS 3.8 defines them by `Character.isJavaIdentifierStart`, which accepts currency symbols such as `€` and any script's letters, and rejects symbols such as `∞`. For the dollar sign, the spec says it "should be used only in mechanically generated source code". A class named `$` has the binary name `WeirdLegalSyntax$$`, which looks like a typo and is the reason the advice exists.

## Gotchas

* **The empty `for` body is a real bug, not a joke.** `for (...);` followed by a block is a classic: the output shows the block ran once, not once per iteration. The same bug with `if (enabled);` runs the block although `enabled` is false, and `while (...);` runs it once after the loop. A constant `while (false);` is rejected as unreachable (last compile-fail block), but a variable condition is not.
* **The URL trick has a limit.** It only works as a statement. Two nested `https:` URLs would reuse one label while it is in scope, which is an error ([049](049-labeled-blocks.md) shows the message).
* **Receiver parameters are rare.** You will meet one only in code that uses type annotations on `this`, for example nullness or ownership checkers.
* **`$` muddies the water.** Nested and anonymous classes already use `$` in their binary names (`DoubleBrace$1` in [050](050-anonymous-classes-var.md)), so stack traces and reflection output for a class called `$` look like a typo.

## When to use it (and when not to)

Almost never. These are corners worth knowing so that you recognize them in old code, in interview puzzles and in a diff someone is trying to sneak past you. Three of them have honest uses: the receiver parameter for type annotation processors, `outer.new Inner()` when you really must create an inner instance from outside (and the better fix is usually a static nested class), and Unicode identifiers in codebases where the domain language is not English, which is a style question and not a technical one.

Do not use the rest. A URL in a method body is a joke on your future self, `int[] a, b[]` is a bug magnet, `i = i++` and `p+++q` are interview puzzles, and `n --> 0` is cute exactly once. If a review comment would be "what does this do", the answer is to rewrite it.

## Related

* [049 · Labeled Blocks: break Out of Anything](049-labeled-blocks.md), the feature that makes the URL compile
* [052 · Unicode Escapes: Hiding Code in Comments](052-unicode-escapes.md), another lexical surprise that happens even earlier than tokenization
* [050 · Anonymous Classes Meet var](050-anonymous-classes-var.md)
* [061 · Boxing and Overloading Traps](../07-puzzlers/061-boxing-overloading.md), for more of what `char` and `int` do to each other

## Sources

* [JLS §3.2: Lexical Translations](https://docs.oracle.com/javase/specs/jls/se25/html/jls-3.html#jls-3.2), the longest possible translation rule
* [JLS §3.8: Identifiers](https://docs.oracle.com/javase/specs/jls/se25/html/jls-3.html#jls-3.8)
* [JLS §8.4: Method Declarations](https://docs.oracle.com/javase/specs/jls/se25/html/jls-8.html#jls-8.4), including the receiver parameter and array brackets after the parameter list
* [JLS §10.2: Array Variables](https://docs.oracle.com/javase/specs/jls/se25/html/jls-10.html#jls-10.2)
* [JEP 456: Unnamed Variables and Patterns](https://openjdk.org/jeps/456)
