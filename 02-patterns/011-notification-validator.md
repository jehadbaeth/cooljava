# 011 · Notification Pattern Validator

> Stop throwing on the first bad field. Collect every problem, then hand the whole list back at once.

**Since:** Java 16 · **Category:** [Design Patterns, Modernized](../README.md#design-patterns-modernized) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

Most validation code looks like this:

```java
if (name == null || name.isBlank()) throw new IllegalArgumentException("name is required");
if (age < 18) throw new IllegalArgumentException("must be an adult");
if (!email.contains("@")) throw new IllegalArgumentException("email is invalid");
```

The user submits a form with three mistakes. They get told about the first one, fix it, submit again, and get told about the second one. Whack-a-mole as a service.

There is a second, quieter problem: a bad form is not exceptional. It is the *expected* outcome of letting humans type things. Martin Fowler puts it bluntly in the article that named this pattern: if a failure is expected behavior, you shouldn't be using exceptions.

## The trick

Pass a small collector object, the **Notification**, through all the checks. Each check *records* a problem instead of throwing. At the end, the caller decides what to do: show all the messages, map them to HTTP 422, or (only now, if it really must) throw one exception that carries everything.

```java
final class Notification {
    private final List<FieldError> errors = new ArrayList<>();

    Notification error(String field, String message) {
        errors.add(new FieldError(field, message));
        return this;
    }
    boolean hasErrors() { return !errors.isEmpty(); }
    List<FieldError> errors() { return List.copyOf(errors); }
}
```

Two refinements make it pleasant in modern Java:

1. **Rules as data.** A rule is a field name, an extractor (`SignUp::email`), a predicate and a message. A validator is just a list of rules, so it can be built fluently and reused.
2. **Guard rules.** Some checks only make sense if an earlier one passed (no point checking the email domain when the email is `null`). A rule can be marked as a *guard* so a failure stops the remaining rules for that field only. Every other field is still checked.

## Full example

```java run
import java.util.*;
import java.util.function.*;

public class NotificationDemo {

    record FieldError(String field, String message) {
        @Override public String toString() { return field + ": " + message; }
    }

    /** Collects problems instead of throwing them. */
    static final class Notification {
        private final List<FieldError> errors = new ArrayList<>();

        Notification error(String field, String message) {
            errors.add(new FieldError(field, message));
            return this;
        }
        boolean hasErrors() { return !errors.isEmpty(); }
        List<FieldError> errors() { return List.copyOf(errors); }

        /** Escape hatch for callers that really want an exception. */
        void throwIfErrors() {
            if (hasErrors()) throw new ValidationException(errors());
        }
    }

    static final class ValidationException extends RuntimeException {
        final List<FieldError> errors;
        ValidationException(List<FieldError> errors) {
            super(errors.size() + " validation error(s): " + errors);
            this.errors = errors;
        }
    }

    /** A rule: "field X, read with this getter, must satisfy this predicate". */
    record Rule<T, V>(String field, Function<T, V> getter, Predicate<? super V> check,
                      String message, boolean guard) {}

    /** A reusable, fluent list of rules. Validating never throws. */
    static final class Validator<T> {
        private final List<Rule<T, ?>> rules = new ArrayList<>();

        static <T> Validator<T> of(Class<T> type) { return new Validator<>(); }

        <V> Validator<T> rule(String field, Function<T, V> getter, Predicate<? super V> check, String message) {
            rules.add(new Rule<>(field, getter, check, message, false));
            return this;
        }

        /** Like rule(), but when it fails the remaining rules of the same field are skipped. */
        <V> Validator<T> guard(String field, Function<T, V> getter, Predicate<? super V> check, String message) {
            rules.add(new Rule<>(field, getter, check, message, true));
            return this;
        }

        Notification validate(T target) {
            var notification = new Notification();
            var brokenFields = new HashSet<String>();
            for (Rule<T, ?> rule : rules) {
                if (brokenFields.contains(rule.field())) continue;
                if (!passes(rule, target)) {
                    notification.error(rule.field(), rule.message());
                    if (rule.guard()) brokenFields.add(rule.field());
                }
            }
            return notification;
        }

        // A helper method captures the wildcard so getter and check agree on V.
        private static <T, V> boolean passes(Rule<T, V> rule, T target) {
            return rule.check().test(rule.getter().apply(target));
        }
    }

    // Small, named, reusable predicates read better than inline lambdas.
    static Predicate<String> notBlank() { return s -> s != null && !s.isBlank(); }
    static Predicate<String> matches(String regex) { return s -> s.matches(regex); }
    static Predicate<Integer> between(int lo, int hi) { return n -> n != null && n >= lo && n <= hi; }

    record SignUp(String name, String email, Integer age, String password) {}

    static final Validator<SignUp> SIGN_UP = Validator.of(SignUp.class)
            .guard("name", SignUp::name, notBlank(), "is required")
            .rule("name", SignUp::name, s -> s.length() <= 20, "must be at most 20 characters")
            .guard("email", SignUp::email, notBlank(), "is required")
            .rule("email", SignUp::email, matches("[^@\\s]+@[^@\\s]+\\.[a-z]{2,}"), "is not a valid address")
            .rule("age", SignUp::age, between(18, 130), "must be between 18 and 130")
            .guard("password", SignUp::password, notBlank(), "is required")
            .rule("password", SignUp::password, p -> p.length() >= 12, "needs at least 12 characters")
            .rule("password", SignUp::password, p -> p.chars().anyMatch(Character::isDigit), "needs a digit");

    public static void main(String[] args) {
        var bad = new SignUp("", "ada@lovelace", 12, "secret");
        Notification n = SIGN_UP.validate(bad);
        System.out.println("valid? " + !n.hasErrors());
        n.errors().forEach(e -> System.out.println("  " + e));

        var good = new SignUp("Ada", "ada@example.org", 33, "correct horse 1");
        System.out.println("valid? " + !SIGN_UP.validate(good).hasErrors());

        // At a boundary that insists on exceptions, convert once, carrying everything.
        try {
            SIGN_UP.validate(new SignUp(null, null, null, null)).throwIfErrors();
        } catch (ValidationException e) {
            System.out.println(e.getMessage());
        }
    }
}
```

Output:

```text output
valid? false
  name: is required
  email: is not a valid address
  age: must be between 18 and 130
  password: needs at least 12 characters
  password: needs a digit
valid? true
4 validation error(s): [name: is required, email: is required, age: must be between 18 and 130, password: is required]
```

## How it works

* `Notification` is the whole pattern. Everything else is convenience. It is a plain accumulator with `error`, `hasErrors` and `errors`, which matches the shape Fowler describes (his version also keeps an optional cause exception per error, which is worth adding if checks can blow up).
* `Rule<T, V>` stores the getter and the predicate with the *same* `V`, so `rule("age", SignUp::age, between(18, 130), ...)` is type checked: passing a `Predicate<String>` for an `Integer` field does not compile.
* The validator keeps a `List<Rule<T, ?>>` because the rules have different value types. The private generic `passes` method is a *wildcard capture helper* (see [035](../04-generics/035-pecs-wildcard-capture.md)): inside it, `V` has a name again, so `check.test(getter.apply(target))` type checks.
* Guards solve the `null` problem without nested `if`s. In the third run every field is `null`, the guards fire, and you get exactly one sensible message per field instead of a `NullPointerException` from `s.length()`.
* The validator is immutable after construction in practice and holds no per-call state, so a single `static final` instance is safe to share across threads.

## Gotchas

* **Order matters for guards.** A guard only protects the rules that come *after* it for the same field. Put the null or blank check first.
* **Cross-field rules** ("password must not contain the name") do not fit the per-field shape. Add a rule whose getter returns the whole object, e.g. `rule("password", s -> s, s -> !s.password().contains(s.name()), "...")`, with a guard on both fields earlier.
* **Messages are not i18n.** For real UIs store a message *key* plus arguments in `FieldError` and render later.
* **Do not let `Notification` leak into your domain model.** Validate at the boundary (controller, command handler), then construct an always-valid domain object. Its constructor can still throw, because at that point invalid data really is a programming error. That is exactly the case Fowler keeps exceptions for.

## When to use it (and when not to)

Use it whenever a human or an external system sends you data that can be wrong in several ways at once: forms, API payloads, CSV imports, configuration files. Users fix everything in one round trip, and your control flow stays boring.

Skip it for internal invariants ("this list must never be empty here"). Those are bugs, and a fast, loud exception is the right tool. Also, if you are already on Jakarta Bean Validation (Hibernate Validator), it *is* a notification pattern: `validator.validate(bean)` returns a `Set<ConstraintViolation>`. Don't rebuild it out of spite; build this when you want plain code, no reflection and no annotations.

## Related

* [004 · Validation: Collect Every Error, Not Just the First](../01-functional/004-validation-applicative.md), the functional twin of this pattern
* [012 · Specification Pattern](012-specification-pattern.md), for composable business rules
* [043 · Records Beyond POJOs](../05-modern-language/043-records-beyond-pojos.md), for validating inside compact constructors
* [087 · Property Names from Method References](../10-jvm-performance/087-serialized-lambda.md), to derive `"email"` from `SignUp::email` automatically

## Sources

* Martin Fowler, [Replacing Throwing Exceptions with Notification in Validations](https://martinfowler.com/articles/replaceThrowWithNotification.html) (2014)
* Martin Fowler, [Notification](https://martinfowler.com/eaaDev/Notification.html)
* [Jakarta Bean Validation specification](https://beanvalidation.org/)
