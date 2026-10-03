# 065 · Initialization Order Puzzlers

> A singleton that wears a size -1930 belt, a constructor that makes a subclass field look `null` before it exists, and a constant that survives a recompile of the class that defined it. Java initializes things in a strict order, and the order is rarely the one you read.

**Since:** Java 8 · **Category:** [Puzzlers and Gotchas](../README.md#puzzlers-and-gotchas) · **Level:** Intermediate · **Verdict:** ✅ Production

## The puzzle

Static fields, static blocks, instance initializers, constructors and constants all run in a well-defined order, and every puzzle below is a question about that order. The traps date from Java 1.0, so nothing here depends on a recent release (Java 8 is just the oldest one the example is compiled against). Four of the sections come from Joshua Bloch and Neal Gafter's *Java Puzzlers*: section 1 is Puzzle 52 ("Sum Fun"), section 2 is Puzzle 49 ("Larger Than Life"), section 3 is Puzzle 51 ("What's the Point?") and the shell demo further down is Puzzle 93 ("Class Warfare").

Predict every line of output, in order. Section 1 sums the numbers 0 to 99 and asks twice. Section 2 asks Elvis for his belt size, in three versions of the same class. Section 3 builds a `ColorPoint` twice and prints a trace. Section 4 reads two static fields of a class that announces its own initialization. Section 5 is two classes that depend on each other.

```java run
public class InitOrder {

    // Section 1: Puzzle 52 "Sum Fun" (Bloch and Gafter), slightly adapted.
    static class Cache {
        static {
            initializeIfNecessary();
        }

        private static int sum;

        static int getSum() {
            initializeIfNecessary();
            return sum;
        }

        private static boolean initialized = false;

        private static synchronized void initializeIfNecessary() {
            if (!initialized) {
                for (int i = 0; i < 100; i++) sum += i;
                initialized = true;
            }
        }
    }

    // Section 2: Puzzle 49 "Larger Than Life", with a fixed year instead of the calendar so the output is stable.
    static class Elvis {
        static final Elvis INSTANCE = new Elvis();
        static final int THIS_YEAR = Integer.parseInt("2026");   // a method call, so not a constant
        final int beltSize;

        private Elvis() { beltSize = THIS_YEAR - 1930; }
    }

    static class ElvisFixed {
        static final int THIS_YEAR = Integer.parseInt("2026");
        static final ElvisFixed INSTANCE = new ElvisFixed();
        final int beltSize;

        private ElvisFixed() { beltSize = THIS_YEAR - 1930; }
    }

    static class ElvisConstant {
        static final ElvisConstant INSTANCE = new ElvisConstant();
        static final int THIS_YEAR = 2026;                       // a constant expression
        final int beltSize;

        private ElvisConstant() { beltSize = THIS_YEAR - 1930; }
    }

    // Section 3: Puzzle 51 "What's the Point?", with a trace added.
    static class Point {
        static { System.out.println("Point: static initializer"); }
        { System.out.println("Point: instance initializer"); }

        private final String name;

        Point(int x, int y) {
            System.out.println("Point: constructor");
            name = describe(x, y);
        }

        protected String describe(int x, int y) { return "[" + x + "," + y + "]"; }

        @Override public String toString() { return name; }
    }

    static class ColorPoint extends Point {
        static { System.out.println("ColorPoint: static initializer"); }

        private final String label = "pt";
        private final String color;
        private int weight = 7;
        { System.out.println("ColorPoint: instance initializer"); }

        ColorPoint(int x, int y, String color) {
            super(x, y);
            System.out.println("ColorPoint: constructor, weight=" + weight);
            this.color = color;
        }

        @Override protected String describe(int x, int y) {
            return super.describe(x, y) + " label=" + label + " color=" + color + " weight=" + weight;
        }
    }

    // Section 4: one constant, one almost-constant, and a class that announces itself.
    static class Lib {
        static final int CONSTANT = 7;
        static final int COMPUTED = Integer.parseInt("8");
        static { System.out.println("  Lib: static initializer"); }
    }

    // Section 5: two classes whose initializers read each other. Tic and Tac mirror Ping and Pong.
    static class Ping { static int n = Pong.n + 1; }
    static class Pong { static int n = Ping.n + 1; }
    static class Tic { static int n = Tac.n + 1; }
    static class Tac { static int n = Tic.n + 1; }

    public static void main(String[] args) {
        System.out.println("-- 1. Sum Fun");
        System.out.println("Cache.getSum() = " + Cache.getSum());

        System.out.println("-- 2. Larger Than Life");
        System.out.println("Elvis:         " + Elvis.INSTANCE.beltSize);
        System.out.println("ElvisFixed:    " + ElvisFixed.INSTANCE.beltSize);
        System.out.println("ElvisConstant: " + ElvisConstant.INSTANCE.beltSize);

        System.out.println("-- 3. What's the Point?");
        System.out.println("first object:");
        Point first = new ColorPoint(4, 2, "purple");
        System.out.println(first);
        System.out.println("second object:");
        new ColorPoint(0, 0, "red");

        System.out.println("-- 4. Constants");
        System.out.println("Lib.CONSTANT = " + Lib.CONSTANT);
        System.out.println("about to read Lib.COMPUTED");
        System.out.println("Lib.COMPUTED = " + Lib.COMPUTED);

        System.out.println("-- 5. Cycles");
        System.out.println("Ping.n=" + Ping.n + " Pong.n=" + Pong.n);
        System.out.println("Tac.n=" + Tac.n + " Tic.n=" + Tic.n);
    }
}
```

Section 6 needs two compiler runs, and only the shell can run it. A class `Words` has three public constants and a class `PrintWords` prints them. After the first compile, `Words` is replaced by a new version and only `Words` is recompiled. What does `PrintWords` print the second time?

```shell
cat > Words.java <<'EOF'
public class Words {
    public static final String FIRST  = "the";
    public static final String SECOND = null;
    public static final String THIRD  = "set";
}
EOF
cat > PrintWords.java <<'EOF'
public class PrintWords {
    public static void main(String[] args) {
        System.out.println(Words.FIRST + " " + Words.SECOND + " " + Words.THIRD);
    }
}
EOF
javac Words.java PrintWords.java
java PrintWords
cat > Words.java <<'EOF'
public class Words {
    public static final String FIRST  = "physics";
    public static final String SECOND = "chemistry";
    public static final String THIRD  = "biology";
}
EOF
javac Words.java
java PrintWords
javap -c PrintWords.class | grep 'Field Words'
```

Section 7 is a question about an enum, and its code is in the answer: an enum constant's constructor adds `name()` to a `static final List` declared in the same enum. Does that compile, and if not, which line does javac blame?

## The answer

```text output
-- 1. Sum Fun
Cache.getSum() = 9900
-- 2. Larger Than Life
Elvis:         -1930
ElvisFixed:    96
ElvisConstant: 96
-- 3. What's the Point?
first object:
Point: static initializer
ColorPoint: static initializer
Point: instance initializer
Point: constructor
ColorPoint: instance initializer
ColorPoint: constructor, weight=7
[4,2] label=pt color=null weight=0
second object:
Point: instance initializer
Point: constructor
ColorPoint: instance initializer
ColorPoint: constructor, weight=7
-- 4. Constants
Lib.CONSTANT = 7
about to read Lib.COMPUTED
  Lib: static initializer
Lib.COMPUTED = 8
-- 5. Cycles
Ping.n=2 Pong.n=1
Tac.n=2 Tic.n=1
```

Section 6, the two-step recompile, prints this (the `grep` keeps only the lines of the `javap` listing that mention `Words`; the two `java PrintWords` runs print one line each):

```text
the null set
the chemistry set
         3: getstatic     #13                 // Field Words.SECOND:Ljava/lang/String;
```

Section 7, the enum, is rejected by javac:

```java compile-fail
import java.util.ArrayList;
import java.util.List;

public class EnumConstructor {
    enum Planet {
        MERCURY, VENUS;

        static final List<String> NAMES = new ArrayList<>();

        Planet() {
            NAMES.add(name());
        }
    }
}
```

```text compile-error
EnumConstructor.java:11: error: illegal reference to static field from initializer
            NAMES.add(name());
            ^
1 error
```

## Why

Two rulebooks decide everything above: JLS 12.4 for classes and JLS 12.5 for instances.

* **A class is initialized on first active use**: the first `new`, the first static method call, or the first read or write of a static field that is not a constant variable. Its superclass is initialized first. Static field initializers and `static { }` blocks then run once, in textual order.
* **An instance starts life with every field zeroed** (`0`, `false`, `null`). The constructor first runs `super(...)`, then the instance field initializers and instance initializer blocks in textual order, and only then the rest of its own body.
* **A constant variable is not read at runtime.** A `final` field of primitive or `String` type that is initialized with a constant expression is copied into the bytecode of every class that uses it (JLS 4.12.4, JLS 13.4.9).

### Section 1: textual order wins

The `static` block sits above the declarations of `sum` and `initialized`. When it runs, `initialized` is still `false` by default, so the loop runs and `sum` becomes 4950. Then the declaration `private static boolean initialized = false;` executes and resets the flag. `sum` has no initializer, so it keeps 4950. The first `getSum()` sees `initialized == false` and adds 4950 again: 9900. The fix is to move the declarations above the block, or to delete `= false`, which only repeats the default.

### Section 2: the singleton that saw a zero

In `Elvis`, `INSTANCE` is the first static initializer, so the constructor runs while `THIS_YEAR` still holds its default `0`, and `0 - 1930` is `-1930`. `Integer.parseInt("2026")` is a method call, so `THIS_YEAR` is not a constant variable and cannot be inlined. `ElvisFixed` declares `THIS_YEAR` first, which is the whole fix. `ElvisConstant` shows the other way out: `2026` is a constant expression, every use is replaced by the literal at compile time, and declaration order no longer matters.

The compiler does not warn here. JLS 8.3.3 forbids reading a static field by simple name before its declaration, but only inside initializers. A read in a constructor or any method is not checked.

### Section 3: the overridable call

Static initializers run once per class, superclass first, and only when the class is first used, which is why they appear after "first object:" and not at all for the second object. For each object the order is: `Point` instance initializer, `Point` constructor, and inside it `describe(...)`, which is virtual and lands in `ColorPoint.describe`. At that moment `ColorPoint` has not run any of its own initializers, so `color` is `null` and `weight` is `0`. Then `ColorPoint`'s initializers run, and its constructor body prints `weight=7`. The same field has two values depending on when you look, and `Point` stored the early look in `name` for good.

`label` is the odd one out: it shows `pt` even though its initializer has not run. It is `final`, a `String` and initialized with a literal, so it is a constant variable and `describe` reads the inlined constant, not the field. Change it to `new String("pt")` and it prints `null` like `color`.

### Section 4: touching a constant does not initialize the class

`Lib.CONSTANT` compiles to the literal `7`, so `Lib` is never initialized by that line. `Lib.COMPUTED` is a real field read: the JVM initializes `Lib` first, the static block prints its message, and only then does the string concatenation finish. That is why the message lands between the two prints.

### Section 5: a class that is being initialized counts as done

The JVM never initializes a class twice, and a class that the current thread is already initializing is treated as ready. Touch `Ping` first: it starts initializing, needs `Pong.n`, so `Pong` starts initializing, reads `Ping.n` (in progress, so still the default `0`), stores `1`, and returns to `Ping`, which stores `2`. Whichever class of a cycle is touched first ends up with the larger value. `Tic` and `Tac` have the same shape, but the line touches `Tac` first, so `Tac.n` is 2 and `Tic.n` is 1. Neither the name nor the position in the source decides it, only the first access.

### Section 6: a constant that outlives its class

`FIRST` and `THIRD` are constant variables, so `PrintWords` contains the literals `"the"` and `"set"` and does not read them from `Words` at all. `null` is not a constant expression, so `SECOND` is a real static field read. The `javap` listing proves it: the only mention of `Words` in `PrintWords` is a `getstatic` of `SECOND`. After `Words` is replaced and recompiled alone, the stale literals stay and the live field moves on: `the chemistry set`. JLS 13.4.9 states this outright: binaries that used a constant keep the old value until they are recompiled.

### Section 7: why the enum constructor is rejected

An enum's constants are the first static initializers, so when a constructor runs, `NAMES` has not been created yet. JLS 8.9.2 therefore makes it a compile-time error to refer to a static field of the enum from a constructor, an instance initializer or an instance variable initializer, unless that field is a constant variable. The usual workaround is a static block placed after the constants, as in `static { for (Planet p : values()) NAMES.add(p.name()); }`, or a lookup map built lazily on first use.

## Gotchas

* **javac only checks the direct textual reference.** In the enum, move `NAMES.add(name())` into an instance method and call that method from the constructor: it compiles, and `Planet` fails at runtime with an `ExceptionInInitializerError` caused by a `NullPointerException`. The same bypass works for the forward-reference rule of JLS 8.3.3. `static int a = Fwd.b + 1; static int b = 2;` compiles and gives `a == 1`, while the plain `b + 1` is rejected as an illegal forward reference.
* **A static initializer that throws poisons the class.** The first use throws `ExceptionInInitializerError` with the original exception as cause. Every later use throws `NoClassDefFoundError: Could not initialize class ...`. On JDK 17 and 25 its cause is a placeholder `ExceptionInInitializerError` that names the original exception, but the original stack trace belongs to the first error only. Look for the first error in the logs, not the last.
* **Class initialization takes a lock.** Two threads that start initializing two classes of a cycle, one each, can deadlock. This is rare, hard to reproduce, and the classic reason to keep static initializers small and free of cross-class dependencies.
* **Constants cross jar boundaries.** A `public static final int` in a library is baked into every client. Bumping the library version without recompiling the clients leaves the old value in place. If a value may change, make it a method or hide it from the constant rules, for example `static final String VERSION = String.valueOf("2.0");`.

## How to stay safe

* **Keep the order of statics boring.** Declare constants and lookup tables first, singletons last. For anything lazy, use the initialization-on-demand holder idiom ([082](../09-concurrency/082-lazy-and-dcl.md)), which makes the JVM's own class initialization lock do the work.
* **Never call an overridable method from a constructor.** Call only `private`, `final` or `static` methods there, or move the work into a static factory that finishes construction first.
* **Since JDK 25 you can set subclass fields before `super(...)`.** With flexible constructor bodies ([046](../05-modern-language/046-flexible-constructor-bodies.md)), a field without an initializer can be assigned in front of the `super` call, so the overridden method sees it:

    ```java
    ColorPoint(int x, int y, String color) {
        this.color = color;     // runs before Point's constructor
        super(x, y);
    }
    ```

  Fields with an initializer, like `weight = 7`, still get their value only after `super(...)` returns.
* **Treat enum constructors as nearly static-free zones.** Fill shared tables in a static block after the constants.
* **Remember what a constant is.** If a value must be read at runtime, do not make it a constant expression. If it is a true constant, recompile everything that uses it.

## Related

* [066 · The Element That Vanished from the HashSet](066-vanishing-hashset.md)
* [082 · Lazy Initialization: Double-Checked Locking, Holders and Lazy Constants](../09-concurrency/082-lazy-and-dcl.md)
* [046 · Flexible Constructor Bodies: Code Before super()](../05-modern-language/046-flexible-constructor-bodies.md)
* [057 · final Isn't Final (Yet)](../06-hidden-corners/057-final-isnt-final.md)

## Sources

* Joshua Bloch and Neal Gafter, *Java Puzzlers: Traps, Pitfalls, and Corner Cases*, Addison-Wesley, 2005 (puzzles 49, 51, 52 and 93)
* [Java Language Specification, chapter 12: Execution](https://docs.oracle.com/javase/specs/jls/se25/html/jls-12.html), sections 12.4 (initialization of classes) and 12.5 (creation of instances)
* [Java Language Specification, chapter 13: Binary Compatibility](https://docs.oracle.com/javase/specs/jls/se25/html/jls-13.html), section 13.4.9 (`final` fields and constants)
* [Java Language Specification, chapter 8: Classes](https://docs.oracle.com/javase/specs/jls/se25/html/jls-8.html), sections 8.3.3 (forward references) and 8.9.2 (enum body declarations)
* [JEP 513: Flexible Constructor Bodies](https://openjdk.org/jeps/513)
