# 040 · Algebraic Data Types with Sealed Interfaces and Records

> Records multiply, sealed interfaces add, and when the arithmetic is right the compiler refuses to let a declined payment have a fee.

**Since:** Java 21 · **Category:** [Modern Language Features](../README.md#modern-language-features) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

Here is a payment as many codebases model it: one class, a status field, and a pile of fields that are "only set when":

```java
class Payment {
    Status status;            // PENDING, AUTHORIZED, CAPTURED, DECLINED
    Money amount;
    String cardLast4;         // only for cards
    YearMonth cardExpiry;     // only for cards
    String iban;              // only for bank transfers
    String voucherCode;       // only for vouchers
    Money voucherBalance;     // only for vouchers
    String authCode;          // only once authorized
    Money fee;                // only once captured
    String declineReason;     // only if declined
}
```

Count the shapes. Four statuses times eight fields that may or may not be `null` gives 4 × 2⁸ = 1,024 combinations. Exactly 12 of them mean something (3 payment methods × 4 states). The other 1,012 are bugs that have not happened yet: a captured payment with no auth code, a card payment with an IBAN, a declined payment that charged a fee. Every method that touches this class has to re-check which combination it got, and nobody checks all of them.

## The trick

Model the data so that the illegal combinations cannot be written down. Yaron Minsky's slogan for this, from his talks on ML at Jane Street, is **"make illegal states unrepresentable"**. Java 21 has exactly the two tools you need:

* A **record** is a *product type*: a `Money` is an amount **and** a currency. Its number of possible values is the product of its components' counts.
* A **sealed interface** with a fixed list of implementations is a *sum type*: a payment method is a card **or** a transfer **or** a voucher. Its count is the sum of its cases.

That arithmetic is why they are called *algebraic* data types. Write the domain as a sum of products and the count comes out right by construction:

```java
sealed interface Method permits Card, BankTransfer, Voucher {}        // 3 shapes
record Card(String last4, YearMonth expires) implements Method {}
record BankTransfer(String iban) implements Method {}
record Voucher(String code, Money balance) implements Method {}

sealed interface Payment permits Pending, Authorized, Captured, Declined {}   // 4 × 3 = 12 shapes
record Captured(Money amount, Method method, String authCode, Money fee) implements Payment {}
```

A `Captured` without an auth code is now a compile error, not a code review comment. And because the compiler knows the complete list of cases, a `switch` over them needs no `default`, which turns out to be the most valuable part.

## Full example

```java run
import java.time.YearMonth;
import java.util.List;

public class PaymentAdt {

    // Product type: an amount AND a currency, validated once at construction.
    record Money(long cents, String currency) {
        Money {
            if (cents < 0) throw new IllegalArgumentException("negative amount: " + cents);
            if (!currency.matches("[A-Z]{3}")) throw new IllegalArgumentException("bad currency: " + currency);
        }
        static Money of(long cents, String currency) { return new Money(cents, currency); }
        Money times(long numerator, long denominator) {
            return new Money(cents * numerator / denominator, currency);
        }
        @Override public String toString() { return "%d.%02d %s".formatted(cents / 100, cents % 100, currency); }
    }

    // Sum type: a payment method is exactly one of these three.
    sealed interface Method permits Card, BankTransfer, Voucher {}
    record Card(String last4, YearMonth expires) implements Method {}
    record BankTransfer(String iban) implements Method {}
    record Voucher(String code, Money balance) implements Method {}

    // The lifecycle is a sum of products: each state carries only the data that exists in it.
    sealed interface Payment permits Pending, Authorized, Captured, Declined {}
    record Pending(Money amount, Method method) implements Payment {}
    record Authorized(Money amount, Method method, String authCode) implements Payment {}
    record Captured(Money amount, Method method, String authCode, Money fee) implements Payment {}
    record Declined(Money amount, Method method, String reason) implements Payment {}

    // Transitions accept only the state they make sense for: capture(pending) does not compile.
    static Payment authorize(Pending p, YearMonth today) {
        return switch (p.method()) {
            case Card(var last4, var expires) when expires.isBefore(today) ->
                    new Declined(p.amount(), p.method(), "card *" + last4 + " expired " + expires);
            case Voucher(var code, var balance) when balance.cents() < p.amount().cents() ->
                    new Declined(p.amount(), p.method(), "voucher " + code + " only holds " + balance);
            case Card c -> new Authorized(p.amount(), c, "AUTH-" + c.last4());
            case BankTransfer t -> new Authorized(p.amount(), t, "SEPA-" + t.iban().substring(0, 4));
            case Voucher v -> new Authorized(p.amount(), v, "VOUCHER-" + v.code());
        };
    }

    static Captured capture(Authorized a) {
        return new Captured(a.amount(), a.method(), a.authCode(), fee(a.amount(), a.method()));
    }

    // Exhaustive and default-free: a fourth Method makes this method stop compiling.
    static Money fee(Money amount, Method method) {
        return switch (method) {
            case Card c -> amount.times(15, 1000);                                      // 1.5 %
            case BankTransfer(var iban) when iban.startsWith("DE") -> Money.of(0, amount.currency());
            case BankTransfer t -> Money.of(35, amount.currency());                     // flat, abroad
            case Voucher v -> Money.of(0, amount.currency());
        };
    }

    static String label(Method method) {
        return switch (method) {
            case Card(var last4, var expires) -> "card *" + last4;
            case BankTransfer(var iban) -> "transfer " + iban;
            case Voucher(var code, var balance) -> "voucher " + code;
        };
    }

    static String describe(Payment payment) {
        return switch (payment) {
            case Pending(var amount, var m) -> "PENDING    " + amount + " by " + label(m);
            case Authorized(var amount, var m, var code) -> "AUTHORIZED " + amount + " by " + label(m) + " [" + code + "]";
            case Captured(var amount, var m, var code, var fee) ->
                    "CAPTURED   " + amount + " by " + label(m) + " [" + code + "], fee " + fee;
            case Declined(var amount, var m, var reason) -> "DECLINED   " + amount + " by " + label(m) + ": " + reason;
        };
    }

    public static void main(String[] args) {
        var today = YearMonth.of(2026, 10);
        var orders = List.of(
                new Pending(Money.of(12_000, "EUR"), new Card("4242", YearMonth.of(2028, 1))),
                new Pending(Money.of(12_000, "EUR"), new Card("1881", YearMonth.of(2026, 9))),
                new Pending(Money.of(50_000, "EUR"), new BankTransfer("DE89370400440532013000")),
                new Pending(Money.of(50_000, "EUR"), new BankTransfer("FR7630006000011234567890189")),
                new Pending(Money.of(2_500, "EUR"), new Voucher("XMAS", Money.of(2_000, "EUR"))));

        for (Pending order : orders) {
            Payment result = authorize(order, today);
            if (result instanceof Authorized ok) result = capture(ok);
            System.out.println(describe(result));
        }

        // Validate at the boundary: a bad Money never exists, so nothing downstream checks again.
        parseMoney(-5, "EUR");
        parseMoney(500, "euro");
    }

    static void parseMoney(long cents, String currency) {
        try {
            System.out.println("accepted: " + Money.of(cents, currency));
        } catch (IllegalArgumentException e) {
            System.out.println("rejected: " + e.getMessage());
        }
    }
}
```

Output:

```text output
CAPTURED   120.00 EUR by card *4242 [AUTH-4242], fee 1.80 EUR
DECLINED   120.00 EUR by card *1881: card *1881 expired 2026-09
CAPTURED   500.00 EUR by transfer DE89370400440532013000 [SEPA-DE89], fee 0.00 EUR
CAPTURED   500.00 EUR by transfer FR7630006000011234567890189 [SEPA-FR76], fee 0.35 EUR
DECLINED   25.00 EUR by voucher XMAS: voucher XMAS only holds 20.00 EUR
rejected: negative amount: -5
rejected: bad currency: euro
```

Now add a fourth payment method. The compiler walks you to every place that needs a decision, and it is just as instructive where it stays silent:

```java compile-fail
import java.time.YearMonth;

public class NewVariant {
    sealed interface Method permits Card, BankTransfer, Voucher, Crypto {}
    record Card(String last4, YearMonth expires) implements Method {}
    record BankTransfer(String iban) implements Method {}
    record Voucher(String code) implements Method {}
    record Crypto(String wallet) implements Method {}            // the new variant

    static long feeCents(long amountCents, Method method) {
        return switch (method) {
            case Card c -> amountCents * 15 / 1000;
            case BankTransfer t -> 35;
            case Voucher v -> 0;
        };
    }

    static String label(Method method) {
        return switch (method) {
            case Card c -> "card *" + c.last4();
            default -> "something else";                         // swallows Crypto without a word
        };
    }

    public static void main(String[] args) {
        System.out.println(label(new Crypto("0xC0FFEE")) + " " + feeCents(100, new Voucher("V")));
    }
}
```

```text compile-error
NewVariant.java:11: error: the switch expression does not cover all possible input values
        return switch (method) {
               ^
1 error
```

## How it works

* **`sealed ... permits`** closes the hierarchy. Only the listed types may implement `Method`, and records are implicitly `final`, so nobody can sneak in a fifth case from another file. That closed list is what the compiler uses to prove a `switch` exhaustive.
* **Record patterns** (`case Card(var last4, var expires)`) deconstruct a value and bind its components in one step. Combined with a `when` guard, the business rule ("expired cards are declined") reads like the sentence it came from. Guards and record patterns in `switch` are final in Java 21 (JEP 440 and 441), which is why the badge says 21 even though sealed types arrived in 17.
* **Transitions as typed functions.** `capture(Authorized a)` cannot be handed a `Pending`. The lifecycle lives in the signatures, much like the phantom type state machine in [030](../04-generics/030-phantom-types.md), but here each state also carries different data.
* **The four principles** of data oriented programming that Brian Goetz lists are all in the example: model the data, the whole data and nothing but the data (no status flag plus nullable fields); data is immutable (records); validate at the boundary (`Money`'s compact constructor rejected both bad inputs); make illegal states unrepresentable (the sealed hierarchy).
* **Exhaustiveness is checked, not assumed.** When the compiler accepts a `switch` without `default` over a sealed type, it also inserts a hidden default that throws `MatchException`. That only fires if a class file changed after compilation (separate compilation), so in a normal build it is unreachable.

## Gotchas

* **`default` turns the alarm off.** In the compile-fail block only `feeCents` breaks. `label` compiles happily and will describe every crypto payment as "something else" forever. On sealed types, list the cases and leave `default` out unless "everything else" is really what you mean.
* **Old style enum switches are not checked either.** A `switch` *statement* with `case RED:` labels over an enum compiles fine when you add a constant. Switch expressions and any `switch` that uses patterns must be exhaustive; classic statements do not. Prefer the arrow form and expressions.
* **Records validate, but they do not encapsulate.** Every component has a public accessor and `toString` prints all of it. A record holding a full card number will happily log it. Store the last four digits, or override `toString`.
* **`permits` across packages needs a module.** In the unnamed module all permitted subclasses must live in the same package as the sealed type. Nested records, as here, avoid the question.
* **Don't model behavior this way by reflex.** If new *operations* are rare and new *variants* are frequent (plugins, third-party payment providers), classic polymorphism is the better fit. Sealed types are best when the set of cases is stable and the set of operations grows. That trade-off is the expression problem, explored in [019](../02-patterns/019-visitor-vs-sealed.md).

## When to use it (and when not to)

Use it for domain data with a fixed set of shapes: payment methods, order states, API responses (`Ok`, `NotFound`, `Error`), parse trees, commands and events. Your reward is that "what happens when we add X?" gets answered by the compiler, in a list, with line numbers.

Skip it at system boundaries where the set of cases is open (data from a newer version of a remote service, user plugins), and for entities with real identity and long mutable lifecycles where JPA or a similar framework owns the class. There, keep the ADT as the internal model and map to it after validation.

## Related

* [019 · The Visitor Pattern Is Dead, Long Live Sealed Types](../02-patterns/019-visitor-vs-sealed.md)
* [041 · Pattern Matching for switch: The Complete Toolkit](041-switch-pattern-matching.md)
* [042 · Symbolic Differentiation with Record Patterns](042-record-patterns-simplifier.md), an ADT for algebra itself
* [016 · State Machines with Enums and Sealed Types](../02-patterns/016-state-machines.md)

## Sources

* Brian Goetz, [Data Oriented Programming in Java](https://www.infoq.com/articles/data-oriented-programming-java/), InfoQ (2022)
* Yaron Minsky, [Effective ML Revisited](https://blog.janestreet.com/effective-ml-revisited/), Jane Street blog (2011), origin of "make illegal states unrepresentable"
* [JEP 409: Sealed Classes](https://openjdk.org/jeps/409), [JEP 440: Record Patterns](https://openjdk.org/jeps/440) and [JEP 441: Pattern Matching for switch](https://openjdk.org/jeps/441)
* [JLS §14.11.1.1: Exhaustive Switch Blocks](https://docs.oracle.com/javase/specs/jls/se25/html/jls-14.html#jls-14.11.1.1)
