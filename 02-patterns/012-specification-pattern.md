# 012 · Specification Pattern: Business Rules as Composable Predicates

> Write "overdue, worth chasing and not disputed" once, then use that same object to filter a list, explain a rejection and generate a SQL `WHERE` clause.

**Since:** Java 21 · **Category:** [Design Patterns, Modernized](../README.md#design-patterns-modernized) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

Business rules have a habit of being written three times. The batch job that sends invoices to a collection agency has an `if`:

```java
if (invoice.daysOverdue() >= 30 && invoice.amount().compareTo(MIN) >= 0 && !invoice.disputed()) { ... }
```

The repository that loads candidates has the same rule as a SQL string, and the support screen that answers "why was this invoice *not* sent?" has a third version, written by someone else, which disagrees with the other two on whether 30 days means `>` or `>=`.

The rule is a piece of domain knowledge. It deserves a name and a single home.

## The trick

Eric Evans and Martin Fowler called it a **Specification**: an object that answers "does this candidate satisfy me?" and that can be combined with `and`, `or` and `not`. The lightweight version is a functional interface with default combinators:

```java
@FunctionalInterface
interface Specification<T> {
    boolean isSatisfiedBy(T candidate);

    default Specification<T> and(Specification<T> other) { return c -> isSatisfiedBy(c) && other.isSatisfiedBy(c); }
    default Specification<T> or(Specification<T> other)  { return c -> isSatisfiedBy(c) || other.isSatisfiedBy(c); }
    default Specification<T> not()                       { return c -> !isSatisfiedBy(c); }
}
```

That is `java.util.function.Predicate` wearing a domain name tag, and for in-memory filtering it is all you need. Its limit is that a lambda is **opaque**. You can call it, but you cannot look inside it, so you cannot ask it *why* it said no, and you certainly cannot turn it into SQL.

The upgrade is to make the specification **data**: a sealed tree of records. Leaves are the domain's vocabulary (`OverdueAtLeast(30)`), inner nodes are `And`, `Or` and `Not`. The tree knows nothing about evaluation. Each use becomes a separate *interpreter*, a recursive `switch` over the tree:

* `isSatisfiedBy(spec, invoice)` evaluates in memory,
* `whyNot(spec, invoice)` lists the leaves that failed, with the actual values,
* `toSql(spec)` emits a parameterized `WHERE` clause.

Because the tree is sealed, every interpreter's `switch` is exhaustive. Add a new leaf and the compiler walks you to every interpreter that has to learn about it, including the SQL one.

## Full example

```java run
import java.math.BigDecimal;
import java.util.*;
import java.util.stream.*;

public class SpecificationDemo {

    record Invoice(String id, String country, BigDecimal amount, int daysOverdue, boolean disputed) {}

    /** A business rule as a tree of plain data. */
    sealed interface Spec permits Leaf, And, Or, Not {
        default Spec and(Spec other) { return new And(this, other); }
        default Spec or(Spec other) { return new Or(this, other); }
        default Spec not() { return new Not(this); }
    }
    /** The domain vocabulary: one record per kind of rule. */
    sealed interface Leaf extends Spec permits OverdueAtLeast, AmountAtLeast, InCountry, Disputed {}
    record OverdueAtLeast(int days) implements Leaf {}
    record AmountAtLeast(BigDecimal amount) implements Leaf {}
    record InCountry(String code) implements Leaf {}
    record Disputed() implements Leaf {}
    record And(Spec left, Spec right) implements Spec {}
    record Or(Spec left, Spec right) implements Spec {}
    record Not(Spec inner) implements Spec {}

    // Named, reusable rules. This is the vocabulary the business actually speaks.
    static final Spec LONG_OVERDUE = new OverdueAtLeast(30);
    static final Spec WORTH_CHASING = new AmountAtLeast(new BigDecimal("100.00"));
    static final Spec SEND_TO_COLLECTIONS = LONG_OVERDUE.and(WORTH_CHASING).and(new Disputed().not());
    static final Spec DACH = new InCountry("DE").or(new InCountry("AT")).or(new InCountry("CH"));

    // Interpreter 1: evaluate in memory.
    static boolean isSatisfiedBy(Spec spec, Invoice i) {
        return switch (spec) {
            case OverdueAtLeast(int days) -> i.daysOverdue() >= days;
            case AmountAtLeast(BigDecimal min) -> i.amount().compareTo(min) >= 0;
            case InCountry(String code) -> i.country().equals(code);
            case Disputed() -> i.disputed();
            case And(Spec l, Spec r) -> isSatisfiedBy(l, i) && isSatisfiedBy(r, i);
            case Or(Spec l, Spec r) -> isSatisfiedBy(l, i) || isSatisfiedBy(r, i);
            case Not(Spec inner) -> !isSatisfiedBy(inner, i);
        };
    }

    // Interpreter 2: a readable description, for logs and error messages.
    static String describe(Spec spec) {
        return switch (spec) {
            case OverdueAtLeast(int days) -> "overdue >= " + days + " days";
            case AmountAtLeast(BigDecimal min) -> "amount >= " + min;
            case InCountry(String code) -> "country = " + code;
            case Disputed() -> "disputed";
            case And(Spec l, Spec r) -> describe(l) + " and " + describe(r);
            case Or(Spec l, Spec r) -> "(" + describe(l) + " or " + describe(r) + ")";
            case Not(Leaf leaf) -> "not " + describe(leaf);
            case Not(Spec inner) -> "not (" + describe(inner) + ")";
        };
    }

    // Interpreter 3: why did this candidate fail? Only failing branches are reported.
    static List<String> whyNot(Spec spec, Invoice i) {
        if (isSatisfiedBy(spec, i)) return List.of();
        return switch (spec) {
            case Leaf leaf -> List.of("needs " + describe(leaf) + ", was " + actual(leaf, i));
            case And(Spec l, Spec r) -> Stream.concat(whyNot(l, i).stream(), whyNot(r, i).stream()).toList();
            case Or(Spec l, Spec r) -> List.of("needs " + describe(spec) + ", neither holds");
            case Not(Spec inner) -> List.of("needs " + describe(spec) + ", but it is " + describe(inner));
        };
    }

    static String actual(Leaf leaf, Invoice i) {
        return switch (leaf) {
            case OverdueAtLeast o -> i.daysOverdue() + " days";
            case AmountAtLeast a -> i.amount().toString();
            case InCountry c -> i.country();
            case Disputed d -> i.disputed() ? "disputed" : "undisputed";
        };
    }

    // Interpreter 4: SQL. Values become ? parameters, never part of the string.
    record Sql(String where, List<Object> params) {}

    static Sql toSql(Spec spec) {
        return switch (spec) {
            case OverdueAtLeast(int days) -> new Sql("days_overdue >= ?", List.of(days));
            case AmountAtLeast(BigDecimal min) -> new Sql("amount >= ?", List.of(min));
            case InCountry(String code) -> new Sql("country = ?", List.of(code));
            case Disputed() -> new Sql("disputed", List.of());
            case And(Spec l, Spec r) -> join("AND", toSql(l), toSql(r));
            case Or(Spec l, Spec r) -> join("OR", toSql(l), toSql(r));
            case Not(Spec inner) -> {
                Sql s = toSql(inner);
                yield new Sql("NOT (" + s.where() + ")", s.params());
            }
        };
    }

    static Sql join(String op, Sql l, Sql r) {
        var params = new ArrayList<>(l.params());
        params.addAll(r.params());
        return new Sql("(" + l.where() + " " + op + " " + r.where() + ")", List.copyOf(params));
    }

    public static void main(String[] args) {
        var invoices = List.of(
                new Invoice("INV-1", "DE", new BigDecimal("250.00"), 45, false),
                new Invoice("INV-2", "AT", new BigDecimal("80.00"), 60, false),
                new Invoice("INV-3", "FR", new BigDecimal("900.00"), 31, true),
                new Invoice("INV-4", "CH", new BigDecimal("120.00"), 12, false),
                new Invoice("INV-5", "US", new BigDecimal("5000.00"), 90, false));

        System.out.println("rule: " + describe(SEND_TO_COLLECTIONS));
        System.out.println("send: " + invoices.stream()
                .filter(i -> isSatisfiedBy(SEND_TO_COLLECTIONS, i)).map(Invoice::id).toList());

        System.out.println("rejected, with reasons:");
        for (var i : invoices) {
            var reasons = whyNot(SEND_TO_COLLECTIONS, i);
            if (!reasons.isEmpty()) System.out.println("  " + i.id() + ": " + reasons);
        }

        // The very same objects, combined further, drive the database query.
        Spec dachCollections = SEND_TO_COLLECTIONS.and(DACH);
        Sql sql = toSql(dachCollections);
        System.out.println("SELECT * FROM invoice WHERE " + sql.where());
        System.out.println("params: " + sql.params());
        System.out.println("in memory: " + invoices.stream()
                .filter(i -> isSatisfiedBy(dachCollections, i)).map(Invoice::id).toList());
        System.out.println("INV-5 outside DACH: " + whyNot(dachCollections, invoices.get(4)));
    }
}
```

Output:

```text output
rule: overdue >= 30 days and amount >= 100.00 and not disputed
send: [INV-1, INV-5]
rejected, with reasons:
  INV-2: [needs amount >= 100.00, was 80.00]
  INV-3: [needs not disputed, but it is disputed]
  INV-4: [needs overdue >= 30 days, was 12 days]
SELECT * FROM invoice WHERE (((days_overdue >= ? AND amount >= ?) AND NOT (disputed)) AND ((country = ? OR country = ?) OR country = ?))
params: [30, 100.00, DE, AT, CH]
in memory: [INV-1]
INV-5 outside DACH: [needs ((country = DE or country = AT) or country = CH), neither holds]
```

## How it works

* **Two sealed levels.** `Spec` permits `Leaf` plus the three combinators, and `Leaf` permits the four domain rules. A `switch` over `Spec` that lists the four leaf records is exhaustive (the compiler flattens the hierarchy), and `whyNot` can still treat all leaves alike with a single `case Leaf leaf`.
* **The combinators are default methods that build nodes.** `LONG_OVERDUE.and(WORTH_CHASING)` evaluates nothing; it just returns `new And(new OverdueAtLeast(30), new AmountAtLeast(...))`. Building a rule and running it are separate steps, which is the whole reason the tree can be interpreted in more than one way.
* **Each interpreter is one recursive `switch`.** Record patterns (`case And(Spec l, Spec r)`) take the node apart and bind its children, so the recursion reads like the definition of the rule. Patterns nest, too: `describe` uses `case Not(Leaf leaf)` before `case Not(Spec inner)` so that only compound rules get parentheses after `not`.
* **`whyNot` reports only failing branches.** For `And` it recurses into both sides and concatenates, so INV-3 is blamed for its dispute and nothing else. For `Or` and `Not` it reports the whole node, because "neither DE nor AT nor CH" is clearer than three separate complaints, as the INV-5 line shows.
* **The SQL interpreter never concatenates a value.** Every value goes into `params`, in the same left-to-right order as the `?` markers, ready for `PreparedStatement.setObject(n, value)`. Column names come from the interpreter, never from the spec, so a spec cannot inject anything.

### How this differs from the Notification pattern

[011 · Notification Pattern Validator](011-notification-validator.md) looks similar at first sight, since both collect reasons. They solve different problems. A notification validator checks *untrusted input* field by field and hands every error back to whoever typed it. A specification is a *domain decision* ("which invoices go to collections?") that is reused for selection, querying and explanation, usually over data you already trust. Evans and Fowler list exactly those three uses: validation, selection from a collection, and building something to order.

## Gotchas

* **The interpreters must agree, and only tests can prove it.** `isSatisfiedBy` and `toSql` are two implementations of every leaf. The compiler guarantees each leaf is handled, not that `>=` in Java became `>=` in SQL. Run each spec against a small test database and against the same rows in memory, and compare.
* **SQL `NULL` breaks `NOT`.** If `disputed` is nullable, `NOT (disputed)` is `NULL` for those rows and they silently drop out of the result, while the Java side treats them as undisputed. Make the columns `NOT NULL` or emit `COALESCE(disputed, FALSE)`.
* **Deep `Or` chains make deep trees.** Ten countries chained with `or` give a tree ten levels deep and a `WHERE` clause full of parentheses. Add an `InCountries(Set<String>)` leaf that becomes `country IN (?, ?, ?)`.
* **Do not mix the lambda version and the tree version.** As soon as one opaque `Predicate` leaf sneaks into the tree "just for this one case", the SQL interpreter has nothing to translate. Make it a proper leaf or keep it out.
* **Records compare structurally.** Two specs built the same way are `equal`, which is handy for caching prepared statements by spec. It also means `a.and(b)` and `b.and(a)` are *not* equal, although they mean the same thing.

## When to use it (and when not to)

Use the functional interface version freely: it costs nothing and turns anonymous conditions into named, testable domain concepts. Reach for the sealed tree once a rule has to live in more than one place, typically memory plus the database, or when users ask why something did not happen.

In a Spring codebase you already have this pattern: Spring Data JPA's `Specification<T>` builds JPA Criteria predicates and composes them with `and`, `or` and `not`. Do not hand-roll SQL strings there; write a `toCriteria` or jOOQ interpreter instead of `toSql`. And if a rule only ever runs in one `if` statement, a well-named private method is a perfectly good specification.

## Related

* [011 · Notification Pattern Validator](011-notification-validator.md), for collecting every input error at the boundary
* [019 · The Visitor Pattern Is Dead, Long Live Sealed Types](019-visitor-vs-sealed.md), on why a sealed tree plus `switch` beats a visitor for interpreters like these
* [040 · Algebraic Data Types with Sealed Interfaces and Records](../05-modern-language/040-algebraic-data-types.md)
* [042 · Symbolic Differentiation with Record Patterns](../05-modern-language/042-record-patterns-simplifier.md), another tree with several interpreters

## Sources

* Eric Evans and Martin Fowler, [Specifications](https://martinfowler.com/apsupp/spec.pdf), the paper that named the pattern
* [Specification pattern](https://en.wikipedia.org/wiki/Specification_pattern), Wikipedia
* [Spring Data JPA: Specifications](https://docs.spring.io/spring-data/jpa/reference/jpa/specifications.html)
* [JEP 441: Pattern Matching for switch](https://openjdk.org/jeps/441) and [JEP 409: Sealed Classes](https://openjdk.org/jeps/409)
