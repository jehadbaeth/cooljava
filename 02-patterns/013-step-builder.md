# 013 · Step Builder: Compile-Time Required Fields

> A builder that refuses to `build()` until you have set every required field, and lets your IDE's autocomplete tell you which one comes next.

**Since:** Java 16 · **Category:** [Design Patterns, Modernized](../README.md#design-patterns-modernized) · **Level:** Intermediate · **Verdict:** ⚠️ Situational

## The problem

The classic builder (Bloch, *Effective Java*, Item 2) fixes telescoping constructors, but it moves a compile-time guarantee to run time:

```java
Email mail = Email.builder()
        .from("ada@example.org")
        .subject("Status")      // forgot .to(...)
        .build();               // compiles fine, explodes later (or worse, sends to nobody)
```

The constructor used to force you to pass a recipient. The builder happily lets you forget it, and the best it can do is throw `IllegalStateException` from `build()`, which you discover in a test if you are lucky and in production if you are not.

## The trick

Give each required field its own **step interface** whose only method sets that field and returns the *next* step. `build()` lives only on the last step, together with the optional setters:

```java
interface FromStep    { ToStep from(String sender); }
interface ToStep      { MoreToStep to(String recipient); }
interface MoreToStep extends ToStep, SubjectStep {}   // another recipient, or move on
interface SubjectStep { OptionalStep subject(String subject); }
interface OptionalStep {
    OptionalStep cc(String address);
    OptionalStep body(String text);
    Email build();
}
```

A single private class implements all of them, and the public entry point returns only the first interface. Because each method's *return type* decides what can be called next, the order of required calls is part of the type system. Skipping one is not a runtime error; it is a method that does not exist.

The `MoreToStep` line is a nice bonus: interface inheritance lets a step offer "one more of these, or carry on". Here it encodes "at least one recipient" without a single `if`.

## Full example

```java run
import java.util.*;

public class StepBuilderDemo {

    enum Priority { LOW, NORMAL, HIGH }

    record Email(String from, List<String> to, String subject, String body, List<String> cc, Priority priority) {
        Email {
            to = List.copyOf(to);
            cc = List.copyOf(cc);
        }

        // The only way in: you get the first step and nothing else.
        static FromStep builder() { return new Builder(); }

        interface FromStep { ToStep from(String sender); }
        interface ToStep { MoreToStep to(String recipient); }
        interface MoreToStep extends ToStep, SubjectStep {}
        interface SubjectStep { OptionalStep subject(String subject); }
        interface OptionalStep {
            OptionalStep cc(String address);
            OptionalStep body(String text);
            OptionalStep priority(Priority priority);
            Email build();
        }

        // One mutable object implements every step; callers only ever see it through an interface.
        private static final class Builder implements FromStep, MoreToStep, OptionalStep {
            private String from;
            private final List<String> to = new ArrayList<>();
            private String subject;
            private String body = "";
            private final List<String> cc = new ArrayList<>();
            private Priority priority = Priority.NORMAL;

            public ToStep from(String sender) { from = Objects.requireNonNull(sender); return this; }
            public MoreToStep to(String recipient) { to.add(Objects.requireNonNull(recipient)); return this; }
            public OptionalStep subject(String s) { subject = Objects.requireNonNull(s); return this; }
            public OptionalStep cc(String address) { cc.add(address); return this; }
            public OptionalStep body(String text) { body = text; return this; }
            public OptionalStep priority(Priority p) { priority = p; return this; }
            public Email build() { return new Email(from, to, subject, body, cc, priority); }
        }
    }

    public static void main(String[] args) {
        Email minimal = Email.builder()
                .from("ada@example.org")
                .to("charles@example.org")
                .subject("Engine notes")
                .build();
        System.out.println(minimal);

        Email full = Email.builder()
                .from("ada@example.org")
                .to("charles@example.org")
                .to("mary@example.org")          // MoreToStep: as many recipients as you like
                .subject("Note G")
                .priority(Priority.HIGH)         // optional setters, any order
                .cc("archive@example.org")
                .body("See attached table.")
                .build();
        System.out.println(full);

        // The steps exist only for the compiler. At run time there is one object with every method.
        Email.ToStep step = Email.builder().from("ada@example.org");
        System.out.println("ToStep offers:     " + names(Email.ToStep.class.getMethods()));
        System.out.println("runtime class has: " + names(step.getClass().getDeclaredMethods()));

        // Gotcha: every step is the same mutable object, so saved steps alias each other.
        var draft = Email.builder().from("ada@example.org").to("team@example.org").subject("Weekly");
        Email first = draft.cc("boss@example.org").build();
        Email second = draft.build();
        System.out.println("first.cc  = " + first.cc());
        System.out.println("second.cc = " + second.cc() + "  <- leaked from the first email");
    }

    static List<String> names(java.lang.reflect.Method[] methods) {
        return Arrays.stream(methods).map(m -> m.getName() + "()").sorted().toList();
    }
}
```

Output:

```text output
Email[from=ada@example.org, to=[charles@example.org], subject=Engine notes, body=, cc=[], priority=NORMAL]
Email[from=ada@example.org, to=[charles@example.org, mary@example.org], subject=Note G, body=See attached table., cc=[archive@example.org], priority=HIGH]
ToStep offers:     [to()]
runtime class has: [body(), build(), cc(), from(), priority(), subject(), to()]
first.cc  = [boss@example.org]
second.cc = [boss@example.org]  <- leaked from the first email
```

Now forget the recipient, the exact bug from the problem section:

```java compile-fail
import java.util.List;

public class SkippedStep {
    record Email(String from, List<String> to, String subject) {
        static FromStep builder() { return new Builder(); }

        interface FromStep { ToStep from(String sender); }
        interface ToStep { SubjectStep to(String recipient); }
        interface SubjectStep { FinalStep subject(String subject); }
        interface FinalStep { Email build(); }

        private static final class Builder implements FromStep, ToStep, SubjectStep, FinalStep {
            private String from, to, subject;
            public ToStep from(String s) { from = s; return this; }
            public SubjectStep to(String s) { to = s; return this; }
            public FinalStep subject(String s) { subject = s; return this; }
            public Email build() { return new Email(from, List.of(to), subject); }
        }
    }

    public static void main(String[] args) {
        Email mail = Email.builder()
                .from("ada@example.org")
                .subject("Status")
                .build();
    }
}
```

```text compile-error
SkippedStep.java:24: error: cannot find symbol
                .subject("Status")
                ^
  symbol:   method subject(String)
  location: interface ToStep
1 error
```

## How it works

* **The return type is the state.** After `from(...)` the static type of the expression is `ToStep`, and `ToStep` has exactly one method. The compiler is doing the bookkeeping that `build()` would otherwise do with `if (to == null) throw ...`.
* **javac names the step you are stuck in.** The error says it cannot find `method subject(String)` in `location: interface ToStep`, which in practice reads as "you still owe me a recipient". Good step names make that message self-explanatory.
* **The private `Builder` implements every step**, so there is still only one object and no extra allocation per step. The output makes the split visible: through the static type `ToStep` you can see exactly one method, `to()`, while the object behind it has all seven. The interfaces are pure compile-time scaffolding.
* **Optional fields live on the last step** and return that same step, so they can be called in any order and any number of times. Defaults (`body = ""`, `Priority.NORMAL`) are set in the field initializers.
* **The record's compact constructor still copies the lists.** Types guarantee that `to` was called; they do not stop the builder from being reused, which is why `List.copyOf` matters (see the gotcha below).
* **Autocomplete becomes documentation.** The `ToStep offers` line is exactly what your IDE's completion popup shows after `from(...)`: one choice. That is the underrated benefit; the builder teaches its own protocol.

## Gotchas

* **Saved steps alias each other.** The output shows it: `draft` was reused for two emails, and the `cc` added for the first one leaked into the second. Either treat steps as single-use (never store them in variables), or make every step method return a fresh immutable object, which costs one allocation per call.
* **`null` and casts still get through.** `.to(null)` compiles, and so does `((Email.OptionalStep) step).build()`, because the runtime object really does implement every step. The step builder protects honest callers. Keep `Objects.requireNonNull` in the setters, and if a broken `Email` would be costly, let the record's compact constructor check `to.isEmpty()` as a last line of defense.
* **Field order becomes API.** Required fields must be set in the order the steps define. Reordering steps or adding a new required field breaks every caller. That is sometimes the point (a new required field *should* break callers) and sometimes just friction.
* **Boilerplate grows linearly.** N required fields need N step interfaces, plus one for the optional tail. Past five or six required fields, a constructor or a parameter record may simply be clearer.
* **Conditional requirements do not fit well.** "Either `to` or `bcc`, but at least one" can be modelled with branching steps, but the interface graph quickly becomes a puzzle of its own.

## When to use it (and when not to)

Use it for public APIs and SDKs where callers are strangers and a forgotten field is expensive: clients for remote services, configuration objects, test fixtures shared across teams. It shines when there are two to five required fields and several optional ones.

Do not write it by hand more than once. [Jilt](https://github.com/skinny85/jilt) is an annotation processor that generates exactly this structure:

```java
@Builder(style = BuilderStyle.STAGED)
public record Email(String from, String to, String subject, @Opt String body) {}
```

Lombok's `@Builder` generates only classic, unstaged builders. Immutables generates classic ones by default and staged ones with `@Value.Style(stagedBuilder = true)`. For internal code with three fields, a record with a compact constructor is shorter, just as strict about required fields and needs no explanation in code review.

## Related

* [030 · Phantom Types: Let the Compiler Track State](../04-generics/030-phantom-types.md), the same idea with type parameters instead of interfaces
* [031 · Self-Bounded Generics for Inheritable Builders](../04-generics/031-self-bounded-generics.md)
* [014 · Withers: Painless Copies of Immutable Records](014-record-withers.md)
* [043 · Records Beyond POJOs](../05-modern-language/043-records-beyond-pojos.md)

## Sources

* Marco Castigliego, [Step Builder pattern](http://rdafbn.blogspot.com/2012/07/step-builder-pattern_28.html) (2012), the post that named the pattern
* Adam Ruka, [The Type-Safe Builder pattern in Java, and the Jilt library](https://www.endoflineblog.com/type-safe-builder-pattern-in-java-and-the-jilt-library) (2017)
* [Jilt on GitHub](https://github.com/skinny85/jilt), see `BuilderStyle.STAGED` and `@Opt`
* Joshua Bloch, *Effective Java*, 3rd edition, Item 2: "Consider a builder when faced with many constructor parameters"
