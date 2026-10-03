# 045 · Java as a Scripting Language

> `public static void main(String[] args)` was the most recited incantation in programming. Java 25 lets you drop all of it, and one shebang line later your `.java` code is a Unix command.

**Since:** Java 25 · **Category:** [Modern Language Features](../README.md#modern-language-features) · **Level:** Beginner · **Verdict:** ⚠️ Situational

## The problem

A forty line helper in Java used to cost a class, a `public static void main`, a block of imports, a `javac` step and a stray `.class` file, or a whole build project if it grew a second file:

```java
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

public class CountLines {
    public static void main(String[] args) throws IOException {
        List<String> lines = Files.readAllLines(Path.of(args[0]));
        System.out.println(lines.size());
    }
}
```

So teams that write Java all day still write their glue in bash or Python. Four JEPs, landing between Java 11 and Java 25, have removed nearly all of that ceremony.

## The trick

Stack these features and a Java file behaves like a script:

| Feature | JEP | Final in |
|---|---|---|
| `java Hello.java` compiles in memory and runs, plus shebang support | 330 | Java 11 |
| The launched file can use classes from other `.java` files | 458 | Java 22 |
| `import module java.base;` imports every package a module exports | 511 | Java 25 |
| Compact source files: no class declaration, instance `main`, `java.lang.IO` | 512 | Java 25 |

A compact source file is just fields and methods at the top level. The compiler wraps them in an implicitly declared class and imports all 58 packages that `java.base` exports, so `List`, `Map`, `Files`, `Path` and `Collectors` need no import lines:

```java
void main() {
    IO.println("Hello, " + List.of("compact", "source", "files"));
}
```

The badge is Java 25 because that is where compact source files and module imports became final. The source launcher itself has worked since Java 11.

## Full example

A small access log report, written the way you would write a script: no class, no imports, no `static`, inline data in a text block.

```java run
// No class, no imports, no static: a compact source file.
// java.base is imported on demand, so List, Map, Files, Path and Collectors just work.

record Hit(String method, String path, int status, int millis) {
    static Hit parse(String line) {
        String[] f = line.split(" ");
        return new Hit(f[0], f[1], Integer.parseInt(f[2]), Integer.parseInt(f[3]));
    }
}

final String ACCESS_LOG = """
        GET index.html 200 12
        GET orders 200 48
        POST orders 201 95
        GET orders 500 1203
        GET favicon.ico 404 3
        GET index.html 200 9
        GET orders 200 51
        """;

String bar(long count) {
    return "#".repeat((int) count);
}

void main() throws IOException {
    Path dir = Files.createTempDirectory("script");
    Path log = Files.writeString(dir.resolve("access.log"), ACCESS_LOG);
    try {
        List<Hit> hits = Files.readAllLines(log).stream().map(Hit::parse).toList();
        IO.println(hits.size() + " requests in " + log.getFileName());

        Map<Integer, Long> byStatus = hits.stream()
                .collect(Collectors.groupingBy(Hit::status, TreeMap::new, Collectors.counting()));
        byStatus.forEach((status, count) -> IO.println("  %d %s".formatted(status, bar(count))));

        Map<String, IntSummaryStatistics> byPath = hits.stream()
                .collect(Collectors.groupingBy(Hit::path, TreeMap::new, Collectors.summarizingInt(Hit::millis)));
        byPath.forEach((path, stats) -> IO.println("  %-12s hits=%d avg=%4.0f ms max=%4d ms"
                .formatted(path, stats.getCount(), stats.getAverage(), stats.getMax())));

        IO.println("server errors: " + hits.stream().filter(h -> h.status() >= 500).map(Hit::path).toList());
    } finally {
        Files.delete(log);
        Files.delete(dir);
    }

    // The class is still there, just implicit: javac names it after the file, it is final, and main is an instance method.
    Class<?> me = getClass();
    IO.println("implicit class " + me.getName() + ", final=" + Modifier.isFinal(me.getModifiers())
            + ", fields=" + Arrays.stream(me.getDeclaredFields()).map(Field::getName).toList());
}
```

Output:

```text output
7 requests in access.log
  200 ####
  201 #
  404 #
  500 #
  favicon.ico  hits=1 avg=   3 ms max=   3 ms
  index.html   hits=2 avg=  11 ms max=  12 ms
  orders       hits=4 avg= 349 ms max=1203 ms
server errors: [orders]
implicit class Main, final=true, fields=[ACCESS_LOG]
```

Two lines that look fine and are not. The first comes from tutorials written during the previews, the second from an import that brings in more than you asked for:

```java compile-fail
import module java.sql;

void main() {
    println("hello");
    Date epoch = new Date(0);
}
```

```text compile-error
Main.java:4: error: cannot find symbol
    println("hello");
    ^
  symbol:   method println(String)
  location: class Main
Main.java:5: error: reference to Date is ambiguous
    Date epoch = new Date(0);
    ^
  both class java.sql.Date in java.sql and class java.util.Date in java.util match
Main.java:5: error: reference to Date is ambiguous
    Date epoch = new Date(0);
                     ^
  both class java.sql.Date in java.sql and class java.util.Date in java.util match
3 errors
```

### A real script with a shebang

Save this as `topwords`, with no `.java` extension:

```java
#!/usr/bin/env -S java --source 25
// Usage: topwords FILE [N]    prints the N most frequent words in FILE (default 3)

void main(String[] args) throws IOException {
    if (args.length == 0) {
        IO.println("usage: topwords FILE [N]");
        System.exit(2);
    }
    int top = args.length > 1 ? Integer.parseInt(args[1]) : 3;
    Map<String, Long> counts = Files.readAllLines(Path.of(args[0])).stream()
            .flatMap(line -> Arrays.stream(line.toLowerCase(Locale.ROOT).split("\\W+")))
            .filter(word -> !word.isEmpty())
            .collect(Collectors.groupingBy(word -> word, Collectors.counting()));
    counts.entrySet().stream()
            .sorted(Map.Entry.<String, Long>comparingByValue().reversed()
                    .thenComparing(Map.Entry.comparingByKey()))
            .limit(top)
            .forEach(e -> IO.println("%4d  %s".formatted(e.getValue(), e.getKey())));
}
```

Then make it executable and run it like any other command, with JDK 25 first on the `PATH` and `hamlet.txt` holding the first four lines of the famous soliloquy:

```shell
$ java -version 2>&1 | head -1
$ chmod +x topwords
$ ./topwords; echo "exit code $?"
$ ./topwords hamlet.txt 5
```

```text
openjdk version "25.0.4.1" 2026-08-18 LTS
usage: topwords FILE [N]
exit code 2
   4  to
   3  the
   2  be
   2  of
   2  or
```

### More than one file

Since Java 22 the launched file may use classes from other source files. The directory of the launched file is the root of the source tree, so `util.Table` lives in `util/Table.java`. Three files:

`Report.java`, the launched file (a compact source file that imports from a package):

```java
import util.Table;

void main() throws IOException {
    var table = new Table("file", "lines");
    for (String file : List.of("Report.java", "Stats.java", "util/Table.java")) {
        table.add(file, Stats.lines(Path.of(file)));
    }
    IO.print(table);
}
```

`Stats.java`, an ordinary class. Only compact files get `java.base` for free, so this one asks for it:

```java
import module java.base;

class Stats {
    static long lines(Path file) throws IOException {
        try (Stream<String> lines = Files.lines(file)) {
            return lines.count();
        }
    }
}
```

`util/Table.java`:

```java
package util;

import module java.base;

public class Table {
    private final List<String> rows = new ArrayList<>();

    public Table(Object... header) { add(header); }

    public void add(Object... cells) { rows.add("%-16s %5s".formatted(cells)); }

    @Override public String toString() { return String.join("\n", rows) + "\n"; }
}
```

Launch it, check that no class files appear, then drop a file full of nonsense next to it:

```shell
$ find . -name '*.java' | sort
$ java Report.java
$ find . -name '*.class' | wc -l
$ echo 'class Broken { this is not java }' > Broken.java
$ java Report.java | head -2
```

```text
./Report.java
./Stats.java
./util/Table.java
file             lines
Report.java          9
Stats.java           9
util/Table.java     13
       0
file             lines
Report.java          9
```

No build tool, no `javac`, no class files on disk, and `Broken.java` is ignored because nothing references it.

## How it works

* **The implicit class.** A compact source file declares a final top-level class in the unnamed package. javac derives its name from the file, and the output shows `Main` because this example was saved as `Main.java`. It also shows `final=true` and that `ACCESS_LOG` is an ordinary instance field. The `record Hit` becomes a nested member. The JEP calls the generated name implementation specific and says not to rely on it, and the class cannot be instantiated with `new`, so it cannot define an API.
* **Instance main methods.** The launcher prefers a `main(String[])` and falls back to `main()`. If the chosen method is not static, it calls the class's no-argument constructor first and invokes `main` on that object. That is why `main` can call `bar(...)` and `getClass()` without `static` anywhere.
* **`IO` lives in `java.lang`**, so it is visible everywhere, like `String`. It has five static methods (`print`, `println` with and without an argument, `readln` with and without a prompt) built on `System.out` and `System.in`.
* **Module imports** bring in every public top-level type of every package a module exports, including packages of modules it `requires transitive`. Compact files get `import module java.base` for free. Ordinary files can write it themselves, as `Stats.java` and `Table.java` do.
* **The source launcher** (JEP 330) compiles the file in memory and runs it from a class loader that never touches the disk. If the first line starts with `#!`, the launcher ignores it, but only when the file name does not end in `.java`. Such a file enters source-file mode only through `--source N`, which is why the shebang line carries it.
* **`env -S`** splits `java --source 25` into separate arguments. Linux hands everything after the interpreter to it as one argument, so without `-S`, `env` would search for a program literally named `java --source 25`. The launcher has its own accommodation for this: a `--source` option that contains whitespace is split into words, so `#!/opt/jdk-25/bin/java --source 25` works without `env`.
* **Multi-file programs** (JEP 458) compile the other files on demand, searching the launched file's directory as a source root. A file that nothing references is never compiled: a `Broken.java` full of syntax errors next to `Report.java` does not stop the report from running. Shebang scripts are deliberately excluded: they always run as a single file.

## Gotchas

* **Preview tutorials lie now.** In the JDK 23 and 24 previews (JEP 477, JEP 495) the class was `java.io.IO` and compact files imported its methods statically, so a bare `println("hello")` worked. JDK 21 and 22 had no `IO` class at all. Java 25 moved it to `java.lang` and dropped the implicit static import: write `IO.println`, or add `import static java.lang.IO.*;` yourself. The compile-fail block shows the resulting `cannot find symbol`.
* **Module imports can collide.** `import module java.sql` adds `java.sql.Date` next to `java.util.Date`, and every use of `Date` becomes ambiguous (both the type and the constructor call are reported). A single-type import such as `import java.sql.Date;` wins, and so does a package import like `import java.util.*;`, because both shadow module imports.
* **Never call the script `topwords.java`.** A file with the `.java` suffix is compiled as ordinary source, and javac rejects the first line with `error: illegal character: '#'`. And `java topwords` without `--source` looks for a compiled class: `Error: Could not find or load main class topwords`.
* **The shebang finds whatever `java` is first on the `PATH`.** With JDK 17 there, the script dies with `error: invalid value for --source option: 25`. On shared machines, write the absolute path to a JDK 25 launcher into the shebang line instead.
* **Every run pays for javac.** `topwords` takes a bit under half a second of wall clock time on a laptop, almost all of it compilation. That is fine for a tool you run by hand, and painful for one a shell loop calls ten thousand times.
* **No dependency management.** `--class-path 'libs/*'` puts JARs on the class path, but nothing downloads them. If a script needs libraries, JBang fills that gap, or it is time for a real build.
* **Program arguments start after the file name.** `java -Xmx64m Report.java -v` gives `-Xmx64m` to the JVM and `-v` to your `main`.

## When to use it (and when not to)

Use compact source files and the launcher for build and release helpers, data fixups, test fixture generators, quick experiments, and teaching. If your team already reads Java fluently, a typed, debuggable script with `java.nio.file`, `java.net.http` and streams beats two hundred lines of bash with `sed` in the middle. Compact files are also the natural home for a JDK bug reproducer: one file, `java Repro.java`, done.

Do not use them for anything with an API, a test suite or dependencies: as soon as the script grows into a program, give it a named class and a build. Skip Java for tiny glue that runs in tight loops, where half a second of compilation per call adds up, and on machines where you cannot control which JDK is first on the `PATH`.

## Related

* [044 · Text Blocks: Beyond Multiline Strings](044-text-blocks.md), for inline data like the access log above
* [090 · Compile and Run Java at Runtime](../10-jvm-performance/090-runtime-compilation-jshell.md)
* [095 · An HTTP Server and Client in One File, No Dependencies](../11-jdk-gems/095-http-server-and-client.md)
* [098 · The Process API: Pipelines and Process Handles](../11-jdk-gems/098-process-api.md), for scripts that drive other programs

## Sources

* [JEP 512: Compact Source Files and Instance Main Methods](https://openjdk.org/jeps/512)
* [JEP 511: Module Import Declarations](https://openjdk.org/jeps/511)
* [JEP 330: Launch Single-File Source-Code Programs](https://openjdk.org/jeps/330), including the shebang rules
* [JEP 458: Launch Multi-File Source-Code Programs](https://openjdk.org/jeps/458)
* [The `java` launcher (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/specs/man/java.html), section "Using Source-File Mode to Launch Source-Code Programs"
