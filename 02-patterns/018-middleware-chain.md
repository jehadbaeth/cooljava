# 018 · Middleware Chains: Chain of Responsibility as Function Composition

> A handler is a function. A middleware is a function from handler to handler. Everything else, from logging to auth to retries, is one `reduce` away.

**Since:** Java 16 · **Category:** [Design Patterns, Modernized](../README.md#design-patterns-modernized) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

Cross-cutting concerns pile up in request handlers:

```java
Response getOrders(Request req) {
    log.info("-> " + req);
    if (!tokens.contains(req.token())) return unauthorized();
    long start = clock.millis();
    try {
        return ok(orders.findAll());     // the actual work: one line out of ten
    } finally {
        metrics.record(clock.millis() - start);
    }
}
```

Copy that into thirty handlers and you have thirty slightly different versions of the same four concerns. The Gang of Four answer, Chain of Responsibility, links handler objects with a `setNext()` method, which works but needs one class per link and makes the order of the chain hard to see.

## The trick

Use the definition from Clojure's Ring library, where this idea is everyday practice: *a middleware is a function that takes a handler and returns a new handler that calls the original one*. In Java:

```java
interface Handler extends Function<Request, Response> {}
interface Middleware extends UnaryOperator<Handler> {}

Middleware logging = next -> request -> {
    log.add("-> " + request.route());
    Response response = next.apply(request);
    log.add("<- " + response.status());
    return response;
};
```

Code before `next.apply` runs on the way in, code after it runs on the way out, and not calling `next` at all **short-circuits** the chain. Composing a list of middlewares is function composition, so it is a `reduce` with the identity middleware `next -> next` as the starting value:

```java
middlewares.stream().reduce(next -> next, (outer, inner) -> next -> outer.apply(inner.apply(next)));
```

The first middleware in the list becomes the outermost layer, like the first filter in a servlet chain or the first `app.use(...)` in Express.

## Full example

```java run
import java.util.*;
import java.util.function.*;

public class MiddlewareDemo {

    record Request(String method, String route, Map<String, String> headers) {}
    record Response(int status, String body) {}

    /** A handler turns a request into a response. */
    interface Handler extends Function<Request, Response> {}

    /** A middleware wraps a handler in another handler. */
    interface Middleware extends UnaryOperator<Handler> {
        /** The first middleware in the list ends up outermost. */
        static Middleware chain(List<Middleware> middlewares) {
            return middlewares.stream().reduce(next -> next, (outer, inner) -> next -> outer.apply(inner.apply(next)));
        }
    }

    static Middleware logging(List<String> log) {
        return next -> req -> {
            log.add("-> " + req.method() + " " + req.route());
            Response res = next.apply(req);
            log.add("<- " + res.status() + " " + req.route());
            return res;
        };
    }

    static Middleware auth(Set<String> validTokens) {
        return next -> req -> validTokens.contains(req.headers().getOrDefault("token", ""))
                ? next.apply(req)
                : new Response(401, "unauthorized");      // short circuit: next is never called
    }

    static Middleware timing(LongSupplier clock, List<String> log) {
        return next -> req -> {
            long start = clock.getAsLong();
            Response res = next.apply(req);
            log.add("   " + req.route() + " took " + (clock.getAsLong() - start) + " ms");
            return res;
        };
    }

    static Middleware retry(int maxAttempts, IntConsumer sleeper) {
        return next -> req -> {
            Response res = next.apply(req);
            for (int attempt = 1; attempt < maxAttempts && res.status() == 503; attempt++) {
                sleeper.accept(100 << (attempt - 1));     // 100 ms, 200 ms, 400 ms, ...
                res = next.apply(req);
            }
            return res;
        };
    }

    public static void main(String[] args) {
        long[] now = {0};                                 // a fake clock in milliseconds
        List<Integer> sleeps = new ArrayList<>();
        IntConsumer fakeSleep = ms -> { sleeps.add(ms); now[0] += ms; };
        int[] appCalls = {0};
        int[] flakyFailuresLeft = {2};

        // The application itself knows nothing about logging, auth, timing or retries.
        Handler app = req -> {
            appCalls[0]++;
            now[0] += 25;                                 // every call "takes" 25 ms
            return switch (req.route()) {
                case "orders" -> new Response(200, "[order 42]");
                case "flaky" -> flakyFailuresLeft[0]-- > 0 ? new Response(503, "busy") : new Response(200, "finally");
                default -> new Response(404, "no route " + req.route());
            };
        };

        var log = new ArrayList<String>();
        Handler server = Middleware.chain(List.of(
                logging(log), auth(Set.of("s3cret")), timing(() -> now[0], log))).apply(app);

        System.out.println(server.apply(new Request("GET", "orders", Map.of("token", "s3cret"))));
        System.out.println(server.apply(new Request("GET", "orders", Map.of())));
        System.out.println(server.apply(new Request("GET", "nowhere", Map.of("token", "s3cret"))));
        log.forEach(System.out::println);
        System.out.println("app calls: " + appCalls[0] + " (the 401 never reached it)");

        System.out.println("== logging outside retry");
        log.clear();
        Handler outside = Middleware.chain(List.of(
                logging(log), timing(() -> now[0], log), retry(4, fakeSleep))).apply(app);
        System.out.println(outside.apply(new Request("GET", "flaky", Map.of())));
        log.forEach(System.out::println);
        System.out.println("sleeps: " + sleeps);

        System.out.println("== retry outside logging");
        log.clear();
        flakyFailuresLeft[0] = 2;
        Handler inside = Middleware.chain(List.of(retry(4, fakeSleep), logging(log))).apply(app);
        System.out.println(inside.apply(new Request("GET", "flaky", Map.of())));
        log.forEach(System.out::println);

        System.out.println("== auth outside logging");
        log.clear();
        Handler quiet = Middleware.chain(List.of(auth(Set.of("s3cret")), logging(log))).apply(app);
        System.out.println(quiet.apply(new Request("GET", "orders", Map.of("token", "guess"))));
        System.out.println("log lines for the rejected request: " + log.size());
    }
}
```

Output:

```text output
Response[status=200, body=[order 42]]
Response[status=401, body=unauthorized]
Response[status=404, body=no route nowhere]
-> GET orders
   orders took 25 ms
<- 200 orders
-> GET orders
<- 401 orders
-> GET nowhere
   nowhere took 25 ms
<- 404 nowhere
app calls: 2 (the 401 never reached it)
== logging outside retry
Response[status=200, body=finally]
-> GET flaky
   flaky took 375 ms
<- 200 flaky
sleeps: [100, 200]
== retry outside logging
Response[status=200, body=finally]
-> GET flaky
<- 503 flaky
-> GET flaky
<- 503 flaky
-> GET flaky
<- 200 flaky
== auth outside logging
Response[status=401, body=unauthorized]
log lines for the rejected request: 0
```

## How it works

* **Two functional interfaces, no classes.** `Handler extends Function<Request, Response>` and `Middleware extends UnaryOperator<Handler>` add names, nothing else. Each middleware is a factory method returning `next -> req -> ...`: the outer lambda receives the next handler once, when the chain is built; the inner lambda runs for every request.
* **`reduce` builds the onion.** Starting from the identity middleware, each step wraps the accumulated chain around the next middleware, so `chain(List.of(a, b, c)).apply(app)` is `a.apply(b.apply(c.apply(app)))`. Function composition is associative and `next -> next` is its identity, which is exactly what `reduce` requires.
* **Short-circuiting is just not calling `next`.** The `auth` middleware returns a 401 without touching the rest of the chain. The output proves it: three requests went in, but the application counted only two calls. The unauthorized request was still logged, because `logging` sits outside `auth`.
* **The order of the list is the order of the onion, and it changes behavior.** With logging outside retry, the log shows one request and one final `200`, and timing reports the full 375 ms: three calls of 25 ms plus backoff sleeps of 100 and 200 ms. With retry outside logging, every attempt is logged separately, including both `503`s. With auth outside logging, a rejected request leaves no log line at all. None of these is wrong, but each answers a different question, so choose deliberately.
* **Time is injected.** `timing` reads a `LongSupplier` and `retry` sleeps through an `IntConsumer`, so the demo uses a fake clock and a fake sleeper that only advance a counter. The output is deterministic and the retry test runs in microseconds instead of 300 ms.

### The same idea elsewhere

* **Servlet filters**: `Filter.doFilter(request, response, chain)` with an explicit `chain.doFilter(...)` call instead of `next.apply(...)`. The order comes from the `web.xml` mappings (or Spring's `@Order`), while `@WebFilter` annotations alone leave it unspecified, which is why filter ordering bugs are so common.
* **The JDK's own `com.sun.net.httpserver.Filter`** has the same shape (`doFilter(exchange, chain)`) plus the factories `beforeHandler`, `afterHandler` and `adaptRequest`. See [095](../11-jdk-gems/095-http-server-and-client.md).
* **Express and Koa**: `app.use((req, res, next) => ...)`. Koa's `await next()` is the closest match to the onion above.
* **Ring**: `(defn wrap-logging [handler] (fn [request] ...))`, which is where the "middleware is a function from handler to handler" definition comes from.

## Gotchas

* **The first in the list is the outermost.** Write the list from the outside in, and add a comment. "Why are the 401s not in the access log?" is always an ordering question.
* **Middlewares that change the request must pass the changed one on.** `next.apply(req.withUser(user))`, not `next.apply(req)`. Immutable records make it obvious which version you passed.
* **Exceptions bypass the "after" half.** If the handler throws, code after `next.apply` never runs. Put the after-logic in `finally`, or add an outermost middleware that maps exceptions to `500` responses.
* **Retry only idempotent requests.** The demo retries a `GET`. Retrying a `POST /payments` on a `503` can charge twice; check the method or an idempotency key first.
* **Deep chains make deep stack traces.** Every layer is a lambda frame. That is harmless, but it makes a stack trace of a failing request in a 15-layer chain look scarier than it is.

## When to use it (and when not to)

Use it whenever several handlers share cross-cutting behavior: HTTP servers, message consumers, command buses, RPC clients (where the same onion wraps outgoing calls with auth headers, retries and metrics). It is plain Java, trivial to unit test one middleware at a time, and the composition is visible in one line.

If you are inside a framework that already has filters or interceptors (Servlet, Spring, Micronaut, gRPC), use its mechanism so the framework's ordering and lifecycle rules apply. Do not stack a home-grown onion inside another onion.

## Related

* [017 · Command Pattern with Undo and Redo in Lambdas](017-command-undo.md)
* [022 · Retry with Exponential Backoff and Jitter](../03-build-it-yourself/022-retry-backoff.md), a production-grade version of the retry layer
* [008 · Currying, Partial Application and Function Composition](../01-functional/008-currying-composition.md)
* [095 · An HTTP Server and Client in One File, No Dependencies](../11-jdk-gems/095-http-server-and-client.md)

## Sources

* [Ring Concepts: Middleware](https://github.com/ring-clojure/ring/wiki/Concepts), the handler and middleware definitions
* [Express: Using middleware](https://expressjs.com/en/guide/using-middleware.html)
* [Jakarta Servlet `Filter` Javadoc](https://jakarta.ee/specifications/servlet/6.0/apidocs/jakarta.servlet/jakarta/servlet/filter)
* [`com.sun.net.httpserver.Filter` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/jdk.httpserver/com/sun/net/httpserver/Filter.html)
* [Chain-of-responsibility pattern](https://en.wikipedia.org/wiki/Chain-of-responsibility_pattern), Wikipedia
