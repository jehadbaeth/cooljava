# 002 · Either: Typed Errors Without Exceptions

> A method that returns `Either<OrderError, PricedLine>` cannot lie about how it fails. One that throws can, and usually does.

**Since:** Java 21 · **Category:** [Functional Programming](../README.md#functional-programming) · **Level:** Intermediate · **Verdict:** ⚠️ Situational

## The problem

Here is a perfectly normal service method:

```java
PricedLine price(String input) {
    OrderLine line = parse(input);        // throws NumberFormatException? IllegalArgumentException?
    validate(line);                       // throws ValidationException (unchecked, of course)
    return catalog.lookup(line);          // throws NoSuchElementException, maybe
}
```

The signature promises a `PricedLine`. The truth is "a `PricedLine`, or one of three exceptions, two of which are undocumented, none of which the compiler will remind you about". The caller finds out in production. Checked exceptions would make it honest, but they do not survive a trip through a lambda or a stream (see [037](../04-generics/037-generic-throws-lambdas.md)).

And a typo in an order line is not exceptional. It is Tuesday.

## The trick

Return the failure as a value. An **Either** holds exactly one of two things: a `Left` (by convention the error) or a `Right` (the result; the Haskell docs offer the mnemonic that "right" also means "correct"). It is [001's Maybe](001-maybe-monad.md) where the empty case finally gets to explain itself.

```java
sealed interface Either<L, R> {
    record Left<L, R>(L error) implements Either<L, R> {}
    record Right<L, R>(R value) implements Either<L, R> {}

    default <R2> Either<L, R2> flatMap(Function<? super R, Either<L, R2>> f) {
        return switch (this) {
            case Right<L, R>(R value) -> f.apply(value);
            case Left<L, R>(L error)  -> new Left<>(error);
        };
    }
}
```

Three more methods make it useful: `map` (transform the success), `mapLeft` (transform the error) and `fold` (collapse both cases into one value at the end).

The second half of the trick is to make the `L` itself a **sealed hierarchy** of error records. Now the final `switch` over the error is exhaustive: add a new failure mode and every place that renders errors stops compiling until it handles it. Try getting that from `catch (RuntimeException e)`.

Chaining `flatMap` gives you what Scott Wlaschin calls **railway oriented programming**: two parallel tracks, success and failure. Each step either keeps you on the success track or switches you to the failure track, and once you are on the failure track every later step is skipped.

## Full example

```java run
import java.util.*;
import java.util.function.*;

public class EitherDemo {

    sealed interface Either<L, R> {
        record Left<L, R>(L error) implements Either<L, R> {}
        record Right<L, R>(R value) implements Either<L, R> {}

        static <L, R> Either<L, R> left(L error) { return new Left<>(error); }
        static <L, R> Either<L, R> right(R value) { return new Right<>(value); }

        default <R2> Either<L, R2> flatMap(Function<? super R, Either<L, R2>> f) {
            return switch (this) {
                case Right<L, R>(R value) -> f.apply(value);
                case Left<L, R>(L error) -> left(error);
            };
        }

        default <R2> Either<L, R2> map(Function<? super R, ? extends R2> f) {
            return flatMap(value -> right(f.apply(value)));
        }

        default <L2> Either<L2, R> mapLeft(Function<? super L, ? extends L2> f) {
            return switch (this) {
                case Right<L, R>(R value) -> right(value);
                case Left<L, R>(L error) -> left(f.apply(error));
            };
        }

        default <T> T fold(Function<? super L, ? extends T> onLeft, Function<? super R, ? extends T> onRight) {
            return switch (this) {
                case Right<L, R>(R value) -> onRight.apply(value);
                case Left<L, R>(L error) -> onLeft.apply(error);
            };
        }
    }

    // Every way an order line can fail, as data. The compiler knows this list is complete.
    sealed interface OrderError {}
    record Unparseable(String input, String reason) implements OrderError {}
    record BadQuantity(int quantity) implements OrderError {}
    record UnknownProduct(String sku) implements OrderError {}

    record OrderLine(String sku, int quantity) {}
    record PricedLine(String sku, int quantity, long unitCents) {
        @Override public String toString() {
            long total = unitCents * quantity;
            return "%d x %s = %d.%02d EUR".formatted(quantity, sku, total / 100, total % 100);
        }
    }

    static final Map<String, Long> CATALOG = Map.of("apple", 50L, "kiwi", 35L);
    static final List<String> TRACE = new ArrayList<>();

    // A generic helper with a plain String error. The exception stops right here.
    static Either<String, Integer> parseInt(String text) {
        try {
            return Either.right(Integer.parseInt(text));
        } catch (NumberFormatException e) {
            return Either.left("'" + text + "' is not a number");
        }
    }

    // Step 1: text to OrderLine. mapLeft lifts the String error into the domain error type.
    static Either<OrderError, OrderLine> parse(String input) {
        TRACE.add("parse");
        String[] parts = input.split(" x ");
        if (parts.length != 2) return Either.left(new Unparseable(input, "expected '<sku> x <qty>'"));
        return parseInt(parts[1])
                .<OrderError>mapLeft(reason -> new Unparseable(input, reason))
                .map(quantity -> new OrderLine(parts[0], quantity));
    }

    // Step 2: business rules.
    static Either<OrderError, OrderLine> validate(OrderLine line) {
        TRACE.add("validate");
        return line.quantity() >= 1 && line.quantity() <= 10
                ? Either.right(line)
                : Either.left(new BadQuantity(line.quantity()));
    }

    // Step 3: enrich with data from somewhere else.
    static Either<OrderError, PricedLine> enrich(OrderLine line) {
        TRACE.add("enrich");
        Long cents = CATALOG.get(line.sku());
        return cents == null
                ? Either.left(new UnknownProduct(line.sku()))
                : Either.right(new PricedLine(line.sku(), line.quantity(), cents));
    }

    // The railway: each step runs only if the previous one stayed on the success track.
    static Either<OrderError, PricedLine> price(String input) {
        return parse(input)
                .flatMap(EitherDemo::validate)
                .flatMap(EitherDemo::enrich);
    }

    // At the edge, fold both tracks into one response. No default branch needed.
    static String render(Either<OrderError, PricedLine> result) {
        return result.fold(
                error -> switch (error) {
                    case Unparseable(String input, String reason) -> "400 cannot parse '" + input + "': " + reason;
                    case BadQuantity(int quantity) -> "422 quantity " + quantity + " is not between 1 and 10";
                    case UnknownProduct(String sku) -> "404 no product called '" + sku + "'";
                },
                line -> "200 " + line);
    }

    // Fail fast over a whole list: the first Left wins, the rest is never looked at.
    static <L, A, B> Either<L, List<B>> traverse(List<A> items, Function<A, Either<L, B>> f) {
        var results = new ArrayList<B>();
        for (A item : items) {
            switch (f.apply(item)) {
                case Either.Left<L, B>(L error) -> { return Either.left(error); }
                case Either.Right<L, B>(B value) -> results.add(value);
            }
        }
        return Either.right(List.copyOf(results));
    }

    public static void main(String[] args) {
        for (String input : List.of("apple x 3", "banana", "kiwi x lots", "apple x 99", "durian x 2", "durian x 99")) {
            TRACE.clear();
            String response = render(price(input));
            System.out.printf("%-13s %-25s %s%n", input, TRACE, response);
        }

        TRACE.clear();
        var order = traverse(List.of("apple x 2", "kiwi x 0", "banana", "kiwi x 4"), EitherDemo::price);
        System.out.println("whole order: " + order);
        System.out.println("steps run:   " + TRACE);
    }
}
```

Output:

```text output
apple x 3     [parse, validate, enrich] 200 3 x apple = 1.50 EUR
banana        [parse]                   400 cannot parse 'banana': expected '<sku> x <qty>'
kiwi x lots   [parse]                   400 cannot parse 'kiwi x lots': 'lots' is not a number
apple x 99    [parse, validate]         422 quantity 99 is not between 1 and 10
durian x 2    [parse, validate, enrich] 404 no product called 'durian'
durian x 99   [parse, validate]         422 quantity 99 is not between 1 and 10
whole order: Left[error=BadQuantity[quantity=0]]
steps run:   [parse, validate, enrich, parse, validate]
```

## How it works

* **Right biased.** `map` and `flatMap` only touch the `Right`. A `Left` passes through every later step untouched, which is the whole railway in one `switch` arm: `case Left<L, R>(L error) -> left(error)`. That is exactly 001's `Nothing` case, except the error comes along for the ride, and the same three monad laws hold for the same reason.
* **The trace shows the short circuit.** `banana` never reaches `validate`, `apple x 99` never reaches `enrich`. Steps that are skipped are not "run and ignored", they are not called at all.
* **`durian x 99` has two problems** (unknown product and bad quantity) but reports only the first one the pipeline hits. That is *fail fast*, and it is correct here: there is no point pricing a line you could not validate. When the checks are independent and you want every error at once, you need [004 · Validation](004-validation-applicative.md) instead.
* **`mapLeft` translates errors between layers.** `parseInt` knows nothing about orders and reports a `String`. The parse step lifts it into `Unparseable`, so the pipeline speaks one error language. The explicit `<OrderError>` type witness is needed because Java generics are invariant: an `Either<Unparseable, Integer>` is not an `Either<OrderError, Integer>`.
* **`fold` is the exit.** Inside the pipeline you stay in `Either`. At the boundary (HTTP handler, CLI, message consumer) you fold both tracks into one response, and the inner `switch` over the sealed `OrderError` needs no `default`. Add a `record OutOfStock(...)` and `render` stops compiling until you decide what to tell the user.
* **`traverse`** turns a list of inputs into one `Either` of a list. It returns the first error and does not even look at `banana` or the last line, as the trace shows.

## Gotchas

* **Exceptions still exist.** `Either` covers *expected* failures. A `NullPointerException` inside `enrich` is still a bug and still flies straight past every `flatMap`. Catch exceptions at the edge of the code you control (like `parseInt` above) and convert them there, once.
* **Invariance bites.** Without the `<OrderError>` witness, javac infers `Either<Unparseable, OrderLine>` and refuses to return it. Declaring `flatMap(Function<? super R, ? extends Either<? extends L, ? extends R2>>)` is more flexible but quickly unreadable. Most hand rolled versions accept the occasional witness.
* **`Left` and `Right` are not symmetric names in your head.** A teammate reading `Either<PricedLine, OrderError>` will assume the error is on the right. Stick to the convention, or name your own type `Result<E, T>` with `Ok` and `Err` (Rust's naming) so nobody has to remember.
* **Stack traces are gone.** A `Left(UnknownProduct("durian"))` tells you what went wrong, not where. For domain errors that is fine (you know where: in `enrich`). For anything resembling a bug, keep the exception.
* **No `get()`.** Resist adding one that throws on `Left`. It reintroduces exactly the invisible failure you were trying to get rid of. Use `fold`, or a pattern matching `switch`.

## When to use it (and when not to)

Use `Either` for domain level failures that callers are expected to handle: parsing, validation, lookups that may miss, business rule violations. It shines in pipelines with several steps, in streams, and anywhere the error type deserves to be part of the API.

Do not wrap infrastructure failures (database down, disk full) in it by reflex. Those are usually handled far away, by a retry loop or a 500 page, and exceptions carry them there with a stack trace and zero ceremony. Also be honest about your team: a codebase where half the methods throw and half return `Either` is worse than either style alone. If you want it everywhere, [Vavr](https://vavr.io/) has a battle tested `Either` with the whole toolkit around it.

## Related

* [001 · The Maybe Monad from Scratch](001-maybe-monad.md), the same shape without the error
* [003 · Try: Turning Exceptions into Values](003-try-monad.md), when the error type is simply `Throwable`
* [004 · Validation: Collect Every Error, Not Just the First](004-validation-applicative.md), the accumulating alternative to fail fast
* [040 · Algebraic Data Types with Sealed Interfaces and Records](../05-modern-language/040-algebraic-data-types.md)

## Sources

* Scott Wlaschin, [Railway Oriented Programming](https://fsharpforfunandprofit.com/rop/), slides, video and the original "two track" diagrams
* [`Data.Either` documentation](https://hackage.haskell.org/package/base/docs/Data-Either.html), Haskell base library, where the Left is error, Right is correct convention comes from
* Alexis King, [Parse, don't validate](https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/) (2019), on returning richer types instead of throwing
* [JEP 409: Sealed Classes](https://openjdk.org/jeps/409) and [JEP 441: Pattern Matching for switch](https://openjdk.org/jeps/441)
