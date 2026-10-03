# 046 · Flexible Constructor Bodies: Code Before super()

> Since Java 1.0, the first thing a constructor could do was call `super(...)`, so validation had to hide in static helper methods. Java 25 lets statements run first, as long as they stay away from `this`, except to assign fresh fields.

**Since:** Java 25 · **Category:** [Modern Language Features](../README.md#modern-language-features) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

A constructor must call a superclass or sibling constructor first, so any work on the arguments had to happen inside that call. Validation became a puzzle of static helpers:

```java
class SavingsAccount extends Account {
    private final double rate;

    SavingsAccount(String id, double rate, long cents) {
        super(normalize(id), requirePositive(cents));   // helpers exist only to run before super
        this.rate = rate;                               // too late to reject a bad rate cheaply
    }
}
```

Parsing was worse. A constructor that takes `"3, 4"` and delegates to `this(x, y)` had to split the string once per argument, because there was nowhere to keep a local variable.

The second problem is nastier. A superclass constructor that calls an overridable method runs *before* the subclass has assigned any field, so the override sees `null`, `0` and `false`, even for `final` fields:

```java
class Shape {
    Shape() { System.out.println(describe()); }       // runs first
    String describe() { return "shape"; }
}
class Circle extends Shape {
    private final String label;
    Circle(String label) { super(); this.label = label; }
    @Override String describe() { return "label=" + label; }   // prints label=null
}
```

Effective Java, Item 19, says not to do that. Plenty of real code does it anyway, often by accident.

## The trick

JEP 513 (final in Java 25) removes the rule that `super(...)` or `this(...)` must be the first statement. A constructor body now has two phases:

* The **prologue**: statements before the explicit constructor call.
* The **epilogue**: everything after it, where `this` works as usual.

The prologue is an *early construction context*. It may validate, compute, branch, loop, throw and declare locals. It may not use the object under construction, with one exception that fixes the second problem: it may assign **fields declared in the same class that have no initializer**.

```java
SavingsAccount(String id, double rate, long cents) {
    if (rate < 0 || rate > 0.2) throw new IllegalArgumentException("rate out of range: " + rate);
    String normalized = id.strip().toUpperCase(Locale.ROOT);
    this.rate = rate;                  // field is set before the superclass constructor runs
    super(normalized, cents);
}
```

No helper methods, and the field is already there if `super(...)` calls back into an override.

## Full example

```java run
import java.util.*;

public class FlexibleConstructors {

    // 1. The classic trap, and its fix.
    static class Shape {
        Shape() { System.out.println("  Shape constructor sees " + describe()); }
        String describe() { return "shape"; }
    }

    static class LateLabel extends Shape {
        private final String label;
        LateLabel(String label) {
            super();
            this.label = label;
        }
        @Override String describe() { return "label=" + label; }
    }

    static class EarlyLabel extends Shape {
        private final String label;
        private int samples = 4;          // has an initializer, so it still runs after super()
        EarlyLabel(String label) {
            this.label = label;           // plain assignment to an uninitialized field is allowed
            super();
        }
        @Override String describe() { return "label=" + label + ", samples=" + samples; }
    }

    // 2. Validate and normalize before the superclass sees anything.
    static class Account {
        final String id;
        final long cents;
        Account(String id, long cents) {
            this.id = id;
            this.cents = cents;
        }
    }

    static class SavingsAccount extends Account {
        final double rate;
        SavingsAccount(String id, double rate, long cents) {
            if (rate < 0 || rate > 0.2) throw new IllegalArgumentException("rate out of range: " + rate);
            String normalized = id.strip().toUpperCase(Locale.ROOT);
            this.rate = rate;
            super(normalized, cents);
        }
        @Override public String toString() { return id + " at " + rate + " with " + cents + " cents"; }
    }

    // 3. Compute arguments once, in locals, before delegating with this(...).
    record Point(int x, int y) {
        Point(String text) {
            String[] parts = text.split(",");
            if (parts.length != 2) throw new IllegalArgumentException("expected x,y but got '" + text + "'");
            this(Integer.parseInt(parts[0].strip()), Integer.parseInt(parts[1].strip()));
        }
    }

    // 4. Prologues run bottom-up, epilogues top-down.
    static void trace(String step) { System.out.println("  " + step); }

    static class A {
        A() { trace("A body"); }
    }
    static class B extends A {
        B() { trace("B prologue"); super(); trace("B epilogue"); }
    }
    static class C extends B {
        C() { trace("C prologue"); super(); trace("C epilogue"); }
    }

    public static void main(String[] args) {
        System.out.println("classic trap:");
        new LateLabel("ok");
        System.out.println("fixed:");
        new EarlyLabel("ok");

        System.out.println("validation:");
        System.out.println("  " + new SavingsAccount("  sav-1 ", 0.03, 1_500));
        try {
            new SavingsAccount("sav-2", 0.9, 0);
        } catch (IllegalArgumentException e) {
            System.out.println("  rejected: " + e.getMessage());
        }

        System.out.println("records:");
        System.out.println("  " + new Point(" 3, 4"));
        try {
            new Point("1,2,3");
        } catch (IllegalArgumentException e) {
            System.out.println("  rejected: " + e.getMessage());
        }

        System.out.println("order:");
        new C();
    }
}
```

Output:

```text output
classic trap:
  Shape constructor sees label=null
fixed:
  Shape constructor sees label=ok, samples=0
validation:
  SAV-1 at 0.03 with 1500 cents
  rejected: rate out of range: 0.9
records:
  Point[x=3, y=4]
  rejected: expected x,y but got '1,2,3'
order:
  C prologue
  B prologue
  A body
  B epilogue
  C epilogue
```

The flip side is what the prologue still forbids. This program has four mistakes, and javac rejects every one:

```java compile-fail
public class EarlyThis {
    static class Base {
        Base(Object owner) {}
        String name() { return "base"; }
    }

    static class Child extends Base {
        final String label;
        int retries = 3;

        Child(String label) {
            System.out.println(this.label);
            String n = name();
            retries = 5;
            super(this);
            this.label = label;
        }
    }

    public static void main(String[] args) {
        new Child("x");
    }
}
```

```text compile-error
EarlyThis.java:12: error: cannot reference this before supertype constructor has been called
            System.out.println(this.label);
                               ^
EarlyThis.java:13: error: cannot reference name() before supertype constructor has been called
            String n = name();
                       ^
EarlyThis.java:14: error: cannot assign initialized field 'retries' before supertype constructor has been called
            retries = 5;
            ^
EarlyThis.java:15: error: cannot reference this before supertype constructor has been called
            super(this);
                  ^
4 errors
```

## How it works

* **No JVM change.** The JVM already accepts arbitrary code before the constructor invocation, as long as that code touches the uninitialized object only to assign its fields. It was relaxed years ago to support compiler generated fields for inner classes, and only the Java language kept the stricter rule. JEP 513 therefore changes the language specification and javac, not the JVM specification.
* **Early construction context.** The prologue and the argument list of `super(...)` or `this(...)` share the same rule: no use of `this`, explicit or implicit. That rules out instance fields (`this.label` and plain `label` alike), instance methods, `super.m()`, `new Inner()` for an inner class, and lambdas or anonymous classes that capture `this`. Parameters, locals and static members are all fine, and so is a lambda that captures a parameter.
* **The single exception** is a simple assignment to a field declared in this very class whose declaration has no initializer. Final fields qualify, so a `final String label` can be assigned before `super()` and the superclass constructor then observes the real value, as `EarlyLabel` shows.
* **Initializers still run after `super()`.** `private int samples = 4;` is compiled into the constructor right after the super call, which is why the fixed class prints `samples=0` and `label=ok`. The compiler refuses to let the prologue assign such a field, because the initializer would silently overwrite the value.
* **Order.** With prologues in every constructor, the output shows the whole chain: `C prologue`, `B prologue`, then the body of `A`, then `B epilogue` and `C epilogue`. Prologues run from the most derived class up, epilogues from the base down.
* **Records.** A canonical record constructor still may not contain an explicit constructor call. A non-canonical one must still call `this(...)`. What changed is that it can now compute the arguments in locals first, so `Point(String)` parses once.

## Gotchas

* **Only your own, uninitialized fields.** Assigning a field of the superclass (`this.x = 1` where `x` lives in `Base`) is rejected like any other use of `this`. So is assigning a field that has an initializer, which is the `retries = 5` error above.
* **`return` is not allowed in the prologue.** javac reports `'return' not allowed before explicit constructor invocation`. `throw` is fine, and is the point of the exercise.
* **The constructor call stays unconditional.** It cannot sit inside `if`, `try` or a loop (`explicit constructor invocation not allowed here`), and a second one is `redundant explicit constructor invocation`. Branch before the call and compute the arguments, not the call.
* **This does not make overridable calls in constructors a good idea.** It makes one failure mode survivable. A superclass constructor that calls an override still runs before every field that has an initializer, and before the subclass epilogue. Keep the advice from Item 19.
* **Version.** In Java 22 to 24 this was a preview feature (JEP 447, 482, 492) and needed `--enable-preview`. Java 24's javac says `flexible constructors is a preview feature and is disabled by default`, and Java 25's `javac --release 24` says `flexible constructors is not supported in -source 24`. A library that must still compile on Java 21 cannot use it.
* **Tools lag.** The JEP itself warns of a period of pain while IDEs, linters and other tools learn that a constructor no longer starts with its constructor call.

## When to use it (and when not to)

Use it to fail fast: argument checks, normalization and parsing that would otherwise need a throwaway static method or a duplicated `split`. Use the early field assignment when a superclass you do not control calls overridable methods and you need your state in place first. In records, use it to write parsing and conversion constructors that read like normal code.

Do not use it to hide complicated logic in constructors, and do not treat early assignment as permission to build hierarchies that call overrides from constructors. If a constructor needs many steps or can fail in several ways at once, a factory method or a [step builder](../02-patterns/013-step-builder.md) is still the clearer shape.

## Related

* [043 · Records Beyond POJOs](043-records-beyond-pojos.md), for compact and canonical record constructors
* [011 · Notification Pattern Validator](../02-patterns/011-notification-validator.md), for collecting every error instead of failing at the first
* [013 · Step Builder: Compile-Time Required Fields](../02-patterns/013-step-builder.md)
* [057 · final Isn't Final (Yet)](../06-hidden-corners/057-final-isnt-final.md), another way final fields can be seen changing

## Sources

* [JEP 513: Flexible Constructor Bodies](https://openjdk.org/jeps/513)
* [JLS 8.8.7: Constructor Body](https://docs.oracle.com/javase/specs/jls/se25/html/jls-8.html#jls-8.8.7)
* [JEP 492: Flexible Constructor Bodies (Third Preview)](https://openjdk.org/jeps/492)
* Joshua Bloch, Effective Java, 3rd edition, Item 19: Design and document for inheritance or else prohibit it
