# 095 · An HTTP Server and Client in One File, No Dependencies

> The JDK has shipped an HTTP server since Java 6 and a modern HTTP client since Java 11. Together they make a self-contained service plus its test client in a single source file, with nothing to download.

**Since:** Java 21 · **Category:** [JDK Gems](../README.md#jdk-gems) · **Level:** Intermediate · **Verdict:** ⚠️ Situational

## The problem

You need a small HTTP endpoint: a fake upstream for a test, a health check, a throwaway tool, a way to share a folder with a colleague. The default move is to add a framework, wait for the dependency download, and write a project around three lines of logic.

Then you need something to call it with, and `HttpURLConnection` is still sitting in the JDK from 1997, with its static state and its manual stream handling.

## The trick

Both halves are already in the JDK, and neither needs a dependency:

* **`com.sun.net.httpserver.HttpServer`** lives in the supported `jdk.httpserver` module. Despite the `com.sun` prefix it is a documented, exported API, not an internal one.
* **`java.net.http.HttpClient`** ([JEP 321](https://openjdk.org/jeps/321), Java 11) is immutable, reusable, speaks HTTP/1.1 and HTTP/2, and offers both blocking and asynchronous calls.
* **[JEP 408](https://openjdk.org/jeps/408)** (Java 18) added the `jwebserver` command, `SimpleFileServer`, and the helper classes `HttpHandlers` and `Request` to the server API.

The recipe for a server that never collides with anything: bind to the loopback address on **port 0**, so the operating system picks a free port, and hand every request to a **virtual thread**:

```java
HttpServer server = HttpServer.create(new InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0);
server.setExecutor(Executors.newVirtualThreadPerTaskExecutor());
server.createContext("/ping", HttpHandlers.of(200, Headers.of("Content-Type", "text/plain"), "pong"));
server.start();
int port = server.getAddress().getPort();   // the port the OS picked
```

## Full example

One program with a small JSON API, a static file context, a redirect, and a client that exercises all of it. The server stops in a `finally` block; without that, the run would never end. The pattern works since Java 11 (server since Java 6); this example needs Java 21 because `HttpClient` is `AutoCloseable` from that release on and virtual threads are final.

```java run
import com.sun.net.httpserver.*;
import java.io.IOException;
import java.net.*;
import java.net.http.*;
import java.net.http.HttpResponse.BodyHandlers;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.stream.*;

public class HttpDemo {

    static final String API = "/api/satellites";

    static void send(HttpExchange exchange, int status, String json) throws IOException {
        byte[] body = json.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, body.length);   // a positive length means: exactly this many bytes follow
        exchange.getResponseBody().write(body);
    }

    static String json(String name, int altitudeKm) {
        return "{\"name\":\"" + name + "\",\"altitudeKm\":" + altitudeKm + "}";
    }

    /** GET lists or fetches satellites, POST registers one ("NAME,ALTITUDE" as plain text). */
    static void handleSatellites(HttpExchange exchange, Map<String, Integer> satellites) throws IOException {
        try (exchange) {   // closes the request and response streams
            exchange.getResponseHeaders().set("X-Virtual-Thread", String.valueOf(Thread.currentThread().isVirtual()));
            String name = exchange.getRequestURI().getPath().substring(API.length()).replaceFirst("^/", "");
            switch (exchange.getRequestMethod()) {
                case "GET" -> {
                    if (name.isEmpty()) {
                        send(exchange, 200, satellites.keySet().stream()
                                .map(n -> "\"" + n + "\"").collect(Collectors.joining(",", "[", "]")));
                    } else if (satellites.containsKey(name)) {
                        send(exchange, 200, json(name, satellites.get(name)));
                    } else {
                        send(exchange, 404, "{\"error\":\"unknown satellite\"}");
                    }
                }
                case "POST" -> {
                    String[] parts = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8)
                            .trim().split(",");
                    // Hand-built JSON is only safe because the input is validated first.
                    if (parts.length != 2 || !parts[0].matches("[A-Za-z0-9-]+") || !parts[1].matches("\\d+")) {
                        send(exchange, 400, "{\"error\":\"expected NAME,ALTITUDE\"}");
                    } else {
                        satellites.put(parts[0], Integer.parseInt(parts[1]));
                        exchange.getResponseHeaders().set("Location", API + "/" + parts[0]);
                        send(exchange, 201, json(parts[0], satellites.get(parts[0])));
                    }
                }
                default -> send(exchange, 405, "{\"error\":\"method not allowed\"}");
            }
        }
    }

    static HttpRequest get(URI base, String path) {
        return HttpRequest.newBuilder(base.resolve(path)).timeout(Duration.ofSeconds(5)).GET().build();
    }

    public static void main(String[] args) throws Exception {
        Path webRoot = Files.createTempDirectory("webroot");
        Files.writeString(webRoot.resolve("hello.txt"), "hello from a file");
        Map<String, Integer> satellites = new ConcurrentSkipListMap<>();

        HttpServer server = HttpServer.create(new InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0);
        try (ExecutorService executor = Executors.newVirtualThreadPerTaskExecutor()) {
            server.setExecutor(executor);
            server.createContext("/ping", HttpHandlers.of(200, Headers.of("Content-Type", "text/plain"), "pong"));
            server.createContext("/old", HttpHandlers.of(301, Headers.of("Location", "/ping"), ""));
            server.createContext("/files", SimpleFileServer.createFileHandler(webRoot));
            server.createContext("/boom", exchange -> { throw new IllegalStateException("handler bug"); });
            server.createContext(API, exchange -> handleSatellites(exchange, satellites));
            server.start();
            URI base = URI.create("http://127.0.0.1:" + server.getAddress().getPort());

            try (HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build()) {
                // 1. A blocking call. The server only speaks HTTP/1.1, so the client downgrades from HTTP/2.
                HttpResponse<String> ping = client.send(get(base, "/ping"), BodyHandlers.ofString());
                System.out.println("ping: " + ping.statusCode() + " " + ping.body() + " over " + ping.version());

                // 2. POST with a body, then read back what the server stored.
                for (String line : List.of("ISS,420", "HST,540", "NOAA-19,870")) {
                    HttpRequest post = HttpRequest.newBuilder(base.resolve(API))
                            .header("Content-Type", "text/plain")
                            .POST(HttpRequest.BodyPublishers.ofString(line)).build();
                    HttpResponse<String> created = client.send(post, BodyHandlers.ofString());
                    System.out.println("POST " + line + " -> " + created.statusCode()
                            + ", Location ends with the new name: "
                            + created.headers().firstValue("Location").orElse("").endsWith("/" + line.split(",")[0]));
                }
                System.out.println("list: " + client.send(get(base, API), BodyHandlers.ofString()).body());

                // 3. Asynchronous: three requests in flight at once, collected in a fixed order.
                List<CompletableFuture<String>> pending = Stream.of("ISS", "HST", "VOYAGER")
                        .map(name -> client.sendAsync(get(base, API + "/" + name), BodyHandlers.ofString())
                                .thenApply(r -> name + " -> " + r.statusCode() + " " + r.body()))
                        .toList();
                CompletableFuture.allOf(pending.toArray(CompletableFuture[]::new)).join();
                pending.forEach(f -> System.out.println("async: " + f.join()));

                // 4. Errors are values: a 404 or 400 is a response, not an exception.
                HttpRequest bad = HttpRequest.newBuilder(base.resolve(API))
                        .POST(HttpRequest.BodyPublishers.ofString("no\"quotes,allowed")).build();
                HttpResponse<String> rejected = client.send(bad, BodyHandlers.ofString());
                System.out.println("bad POST -> " + rejected.statusCode() + " " + rejected.body());
                System.out.println("handler ran on a virtual thread: "
                        + rejected.headers().firstValue("X-Virtual-Thread").orElse("?"));

                // 5. Static files, with SimpleFileServer's handler mounted on a context.
                System.out.println("file: " + client.send(get(base, "/files/hello.txt"), BodyHandlers.ofString()).body());
                System.out.println("directory listing mentions hello.txt: "
                        + client.send(get(base, "/files/"), BodyHandlers.ofString()).body().contains("hello.txt"));

                // 6. Redirects are not followed by default.
                System.out.println("redirect, default policy: " + client.send(get(base, "/old"), BodyHandlers.ofString()).statusCode());

                // 7. A handler that throws sends nothing back; the client only sees a broken connection.
                try {
                    client.send(get(base, "/boom"), BodyHandlers.ofString());
                } catch (IOException e) {
                    System.out.println("handler threw -> client got " + e.getClass().getSimpleName());
                }
            }

            try (HttpClient following = HttpClient.newBuilder().followRedirects(HttpClient.Redirect.NORMAL).build()) {
                HttpResponse<String> followed = following.send(get(base, "/old"), BodyHandlers.ofString());
                System.out.println("redirect, Redirect.NORMAL: " + followed.statusCode() + " " + followed.body());
            }
        } finally {
            server.stop(0);   // the dispatcher thread is not a daemon: forget this and the JVM never exits
            try (var files = Files.walk(webRoot)) {
                files.sorted(Comparator.reverseOrder()).forEach(p -> p.toFile().delete());
            }
        }
    }
}
```

Output:

```text output
ping: 200 pong over HTTP_1_1
POST ISS,420 -> 201, Location ends with the new name: true
POST HST,540 -> 201, Location ends with the new name: true
POST NOAA-19,870 -> 201, Location ends with the new name: true
list: ["HST","ISS","NOAA-19"]
async: ISS -> 200 {"name":"ISS","altitudeKm":420}
async: HST -> 200 {"name":"HST","altitudeKm":540}
async: VOYAGER -> 404 {"error":"unknown satellite"}
bad POST -> 400 {"error":"expected NAME,ALTITUDE"}
handler ran on a virtual thread: true
file: hello from a file
directory listing mentions hello.txt: true
redirect, default policy: 301
handler threw -> client got IOException
redirect, Redirect.NORMAL: 200 pong
```

The same server without writing any Java, which is what JEP 408's `jwebserver` is for. It serves one directory, read only, on the loopback address, port 8000 by default (the commands below pick 8123 so they cannot collide with whatever already sits on 8000, `-o none` silences the access log, and `> /dev/null` hides the startup banner, so the output is only the `curl` results):

```shell
mkdir site && echo "hello from the static site" > site/hello.txt
jwebserver -d site -p 8123 -o none > /dev/null &
until curl -s -o /dev/null http://127.0.0.1:8123/hello.txt; do :; done   # wait until the server answers
curl -s -w '\n%{http_code}\n' http://127.0.0.1:8123/hello.txt
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8123/missing.txt
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8123/hello.txt
curl -s -o /dev/null -w '%{http_code}\n' -I http://127.0.0.1:8123/hello.txt
kill %1
```

```text
hello from the static site

200
404
405
200
```

The first request prints the file and, after the blank line (the file's own trailing newline plus the `\n` in the format string), its `200`. The next three are a missing file (`404`), a `POST` (`405`, the server is read only) and a `HEAD` request (`200`). Without the redirect the server also prints three startup lines (a loopback reminder, the directory it serves and the URL), and with the default `-o info` it adds one access log line per request (client address, timestamp, request line, status).

And the Java API behind it, for when a test needs the same thing: `SimpleFileServer.createFileServer(new InetSocketAddress(InetAddress.getLoopbackAddress(), 0), root, SimpleFileServer.OutputLevel.NONE)` returns a ready `HttpServer` for a directory, and `createFileHandler(root)` (used above) gives you just the handler to mount on a context of your own.

## How it works

* **Port 0 plus loopback means no collisions and no exposure.** Binding to port 0 asks the operating system for any free port, and `server.getAddress().getPort()` tells you which one you got. Binding to `InetAddress.getLoopbackAddress()` keeps the server unreachable from other machines, which also keeps firewall pop-ups away. The program never prints the port, because it differs on every run.
* **The executor decides how requests run.** With no executor set, the server runs every handler on its single dispatcher thread (named `HTTP-Dispatcher`), so one slow handler stalls all clients. Passing `Executors.newVirtualThreadPerTaskExecutor()` gives each exchange its own virtual thread, and the `X-Virtual-Thread: true` header in the output proves it. Blocking inside a handler is now cheap, which is exactly what virtual threads are for (see [077](../09-concurrency/077-virtual-threads.md)).
* **A handler is a functional interface.** `HttpHandler.handle(HttpExchange)` has one method, so a lambda is enough. The protocol sequence is fixed: read the request, set response headers, call `sendResponseHeaders(status, length)`, write the body, close. A positive length means exactly that many bytes, `0` means chunked encoding, and `-1` means no body at all. `HttpExchange` is `AutoCloseable`, so `try (exchange)` closes the streams on every path.
* **`HttpHandlers.of` and `SimpleFileServer.createFileHandler` are the JEP 408 helpers.** `HttpHandlers.of(status, headers, body)` is a complete constant response in one line (`/ping`, and the `/old` redirect with its `Location` header). `HttpHandlers.handleOrElse(predicate, handler, fallback)` chains handlers by condition. The file handler serves a directory, with an HTML listing for folders, and answers `404` for files that do not exist.
* **The client is a configured, reusable object.** `HttpClient.newBuilder()` fixes the connect timeout, redirect policy and protocol version. Each `HttpRequest` adds a URI, headers, a method and optionally a per-request timeout. `send` blocks until the response arrives (cheap on a virtual thread), and `sendAsync` returns a `CompletableFuture`. The three `ISS`, `HST`, `VOYAGER` requests run concurrently, and `allOf(...).join()` waits for all of them (more recipes in [080](../09-concurrency/080-completablefuture-cookbook.md)).
* **`BodyHandlers` and `BodyPublishers` choose how bytes become objects.** `ofString()` collects the body into a `String`. There is also `ofLines()` for a lazy stream of lines, `ofFile(path)` to write straight to disk, `ofInputStream()` for large bodies and `discarding()` when you only care about the status. For request bodies, `BodyPublishers.ofString`, `ofFile`, `ofByteArray` and `noBody` mirror them.
* **Failures are in-band or out-of-band, never both.** A `404` or `400` arrives as a normal `HttpResponse`, and the client never throws for an error status. Only transport problems throw: a connect timeout, a reset, or the broken connection that follows an exception in the handler (`IOException`, the `handler threw` line of the output).
* **The `HTTP_2` default explains the `HTTP_1_1` in the output.** The client prefers HTTP/2 and falls back silently when the server does not offer it. The JDK server speaks only HTTP/1.1, so `ping.version()` prints `HTTP_1_1`.
* **`jwebserver` is a one-purpose tool.** It serves static files for local prototyping, testing and debugging, answers only `GET` and `HEAD` (hence the `405` for the `POST`), and binds to loopback unless you pass `-b`. It prints an access log line per request (`-o none` silences it). It is `SimpleFileServer.createFileServer` with a command line.

### HTTP/3

JDK 26 added HTTP/3 to the client through [JEP 517](https://openjdk.org/jeps/517). It is opt-in: the default protocol stays HTTP/2, and you request HTTP/3 with `HttpClient.newBuilder().version(HttpClient.Version.HTTP_3)` or per request. It is a client-only change. The JEP's non-goals say outright that a server-side HTTP/3 implementation is not provided, so the `HttpServer` above remains HTTP/1.1. The enum itself shows the difference between releases:

```java run jdk=27
import java.net.http.HttpClient;
import java.util.Arrays;

public class Versions {
    public static void main(String[] args) {
        System.out.println(Arrays.toString(HttpClient.Version.values()));
    }
}
```

Output:

```text output
[HTTP_1_1, HTTP_2, HTTP_3]
```

On JDK 25 the same program prints only `[HTTP_1_1, HTTP_2]`, and a program that mentions `HTTP_3` does not compile there.

## Gotchas

* **Forgetting `server.stop(0)` hangs the process.** The dispatcher thread is not a daemon, so `main` returns and the JVM keeps running. The example stops the server in `finally`. The virtual thread executor is closed by the surrounding `try`, so the order is also tidy.
* **Context matching changed between JDKs.** On JDK 25 a context matches by plain string prefix: `createContext("/ping", ...)` also answers `/pingpong` (a request to it returns 200), and `/api` would also answer `/apiary`. On JDK 27 the default is path-segment matching: `/pingpong` gets a 404, while `/ping` and `/ping/...` still match. The system property `sun.net.httpserver.pathMatcher` chooses between `pathPrefix` (the new default) and `stringPrefix` (the old behavior). JDK 26 was not checked. Either way the longest matching context wins, so give contexts a trailing slash and check the remaining path in the handler, and the difference stops mattering.
* **A throwing handler is silent.** The server sends nothing, closes the connection and does not log by default. The client sees an `IOException`, as the output shows. Wrap handler bodies in a `try`/`catch` that answers `500`.
* **There is no JSON in the JDK.** The example builds JSON strings by hand, which is only acceptable because input is validated against a strict pattern first. The bad POST shows the rejection. For anything that echoes user text, use a real JSON library or [write a small parser](../03-build-it-yourself/027-json-parser.md).
* **Redirects are off by default.** `HttpClient.Redirect.NEVER` is the default, so `/old` yields a bare `301` unless you build the client with `followRedirects(Redirect.NORMAL)`.
* **There is no request timeout unless you set one.** `connectTimeout` covers only the connection. Without `HttpRequest.timeout(...)`, a server that accepts and then goes silent blocks `send` forever.
* **Do not put it on the open internet.** It has no HTTP/2, no WebSocket support, little tuning and no built-in routing, authentication or rate limiting. It is the right size for tests, tools and internal endpoints. Modular applications built with `jlink` must add `--add-modules jdk.httpserver` explicitly.

## When to use it (and when not to)

The client is production material: `HttpClient` is the standard way to call HTTP from Java without a dependency, and virtual threads make plain blocking `send` a good default. The server is for the cases where bringing a framework would cost more than the feature: a fake upstream in an integration test (port 0 makes parallel test runs safe), a health or metrics endpoint, an admin tool, a quick `jwebserver` to look at generated HTML or share a folder on a local network you trust.

When you need routing, content negotiation, TLS termination, authentication, HTTP/2 on the server side, observability or a team that expects conventions, use a real framework. The point of this document is that you can decide that after trying the JDK first.

## Related

* [077 · Virtual Threads: A Million Threads and the Pinning Trap](../09-concurrency/077-virtual-threads.md), for why one thread per request is fine now
* [080 · CompletableFuture Cookbook](../09-concurrency/080-completablefuture-cookbook.md), for composing `sendAsync` calls
* [045 · Java as a Scripting Language](../05-modern-language/045-java-scripting.md), for running a file like this one directly with `java HttpDemo.java`
* [027 · A JSON Parser with Sealed Types](../03-build-it-yourself/027-json-parser.md), for the part the JDK leaves out

## Sources

* [JEP 321: HTTP Client](https://openjdk.org/jeps/321) and [JEP 408: Simple Web Server](https://openjdk.org/jeps/408)
* [JEP 517: HTTP/3 for the HTTP Client API](https://openjdk.org/jeps/517)
* [`HttpServer` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/jdk.httpserver/com/sun/net/httpserver/HttpServer.html)
* [`HttpClient` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.net.http/java/net/http/HttpClient.html)
* [`jwebserver` tool reference (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/specs/man/jwebserver.html)
