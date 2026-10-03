# 090 · Compile and Run Java at Runtime

> Every JDK ships a Java compiler you can call like a library, and a REPL you can embed like one. Hand them a `String` and get back a loaded class or an evaluated expression, along with the security bill for it.

**Since:** Java 16 · **Category:** [JVM, Reflection and Performance](../README.md#jvm-reflection-and-performance) · **Level:** Advanced · **Verdict:** ⚠️ Situational

## The problem

Sometimes the code you need does not exist until runtime. A pricing engine wants formulas that business users type into a web form. A test tool generates a class per database table. A teaching platform evaluates student snippets. The usual answer is "write an interpreter" or "embed a scripting language".

But the JVM already has a world-class compiler and an optimizing JIT. If you could turn `"x * x - 2"` into a real class, the JIT would compile it to machine code like everything else, and you would not have to write a parser at all.

## The trick

Two JDK modules do it.

**`javax.tools` (Java 6, JSR 199)** exposes javac as an API. `ToolProvider.getSystemJavaCompiler()` returns the same compiler the `javac` command uses. By default it reads and writes files, but everything goes through a `JavaFileManager`, so three small classes keep it all in memory:

* a `SimpleJavaFileObject` whose `getCharContent` returns the source `String`,
* a `ForwardingJavaFileManager` that hands javac a byte-array "file" whenever it wants to write a `.class`,
* a `ClassLoader` that calls `defineClass` on those bytes.

```java
JavaCompiler javac = ToolProvider.getSystemJavaCompiler();
boolean ok = javac.getTask(null, memoryFiles, diagnostics, options, null, List.of(source)).call();
Class<?> type = new MemoryClassLoader(memoryFiles.classes, parent).loadClass("Formula");
```

**`jdk.jshell` (Java 9, JEP 222)** is the engine behind the `jshell` tool, available as a library. It handles everything a REPL needs that plain javac does not: statements and expressions without a class around them, variables that survive between snippets, redefinition, and a value rendered as a string.

```java
try (JShell shell = JShell.builder().executionEngine("local").build()) {
    shell.eval("int answer = 6 * 7;");               // a SnippetEvent with value "42"
}
```

## Full example

Part 1 compiles a user formula into a class that implements `DoubleUnaryOperator`, runs Newton's method on it, and shows what a syntax error looks like. Part 2 drives JShell as an embedded evaluator and shows the security problem in one line.

```java run
import java.io.*;
import java.net.URI;
import java.util.*;
import java.util.function.DoubleUnaryOperator;
import java.util.stream.Collectors;
import javax.tools.*;
import jdk.jshell.*;

public class RuntimeCompilerDemo {

    /** A source file that lives in a String. */
    static final class StringSource extends SimpleJavaFileObject {
        private final String code;

        StringSource(String className, String code) {
            super(URI.create("string:///" + className.replace('.', '/') + Kind.SOURCE.extension), Kind.SOURCE);
            this.code = code;
        }

        @Override public CharSequence getCharContent(boolean ignoreEncodingErrors) { return code; }
    }

    /** A class file that lives in a byte array. */
    static final class ClassBytes extends SimpleJavaFileObject {
        private final ByteArrayOutputStream bytes = new ByteArrayOutputStream();

        ClassBytes(String className) {
            super(URI.create("bytes:///" + className.replace('.', '/') + Kind.CLASS.extension), Kind.CLASS);
        }

        @Override public OutputStream openOutputStream() { return bytes; }
        byte[] toByteArray() { return bytes.toByteArray(); }
    }

    /** Lets javac read the real class path but write every class file into memory. */
    static final class MemoryFileManager extends ForwardingJavaFileManager<StandardJavaFileManager> {
        final Map<String, ClassBytes> classes = new TreeMap<>();

        MemoryFileManager(StandardJavaFileManager delegate) { super(delegate); }

        @Override
        public JavaFileObject getJavaFileForOutput(Location location, String className,
                                                   JavaFileObject.Kind kind, FileObject sibling) {
            return classes.computeIfAbsent(className, ClassBytes::new);
        }
    }

    /** Defines classes from the bytes javac produced, and nothing else. */
    static final class MemoryClassLoader extends ClassLoader {
        private final Map<String, ClassBytes> classes;

        MemoryClassLoader(Map<String, ClassBytes> classes, ClassLoader parent) {
            super(parent);
            this.classes = classes;
        }

        @Override protected Class<?> findClass(String name) throws ClassNotFoundException {
            ClassBytes found = classes.get(name);
            if (found == null) throw new ClassNotFoundException(name);
            byte[] b = found.toByteArray();
            return defineClass(name, b, 0, b.length);
        }
    }

    static Class<?> compile(String className, String source) throws IOException, ClassNotFoundException {
        JavaCompiler javac = ToolProvider.getSystemJavaCompiler();   // null without the jdk.compiler module
        var diagnostics = new DiagnosticCollector<JavaFileObject>();
        try (var files = new MemoryFileManager(javac.getStandardFileManager(diagnostics, Locale.ROOT, null))) {
            boolean ok = javac.getTask(null, files, diagnostics, List.of("-proc:none"), null,
                    List.of(new StringSource(className, source))).call();
            if (!ok) {
                throw new IllegalArgumentException(diagnostics.getDiagnostics().stream()
                        .map(d -> "line " + d.getLineNumber() + ", column " + d.getColumnNumber()
                                + ": " + d.getMessage(Locale.ROOT))
                        .collect(Collectors.joining("; ")));
            }
            System.out.println("javac wrote " + files.classes.keySet());
            var loader = new MemoryClassLoader(files.classes, RuntimeCompilerDemo.class.getClassLoader());
            return loader.loadClass(className);
        }
    }

    /** Turns a formula typed by a user into real, JIT-compilable bytecode. */
    static DoubleUnaryOperator formula(String expression) throws Exception {
        String source = """
                import java.util.function.DoubleUnaryOperator;

                public class Formula implements DoubleUnaryOperator {
                    @Override public double applyAsDouble(double x) {
                        return %s;
                    }
                    static final class Unused {}   // one source file, two class files
                }
                """.formatted(expression);
        Class<?> type = compile("Formula", source);
        return (DoubleUnaryOperator) type.getDeclaredConstructor().newInstance();
    }

    public static void main(String[] args) throws Exception {
        // Part 1: javax.tools, from a String to a loaded class.
        DoubleUnaryOperator f = formula("x * x - 2");
        System.out.println("f(3) = " + f.applyAsDouble(3) + ", class " + f.getClass().getName()
                + ", loader " + f.getClass().getClassLoader().getClass().getSimpleName());

        // Newton's method on the compiled function finds the square root of 2.
        double x = 1;
        for (int i = 0; i < 5; i++) {
            double slope = (f.applyAsDouble(x + 1e-6) - f.applyAsDouble(x - 1e-6)) / 2e-6;
            x -= f.applyAsDouble(x) / slope;
        }
        System.out.printf("root of f: %.12f%n", x);

        try {
            formula("x * * 2");
        } catch (IllegalArgumentException e) {
            System.out.println("rejected: " + e.getMessage());
        }

        // Part 2: jdk.jshell, a REPL as a library. "local" runs snippets inside this JVM.
        try (JShell shell = JShell.builder().executionEngine("local").build()) {
            List<String> snippets = List.of(
                    "int answer = 6 * 7;",
                    "String greet(String name) { return \"Hello, \" + name; }",
                    "greet(\"Duke\")",
                    "Math.sqrt(2) * Math.sqrt(2)",
                    "answer = \"forty-two\";",
                    "Integer.parseInt(\"forty-two\")",
                    "System.setProperty(\"who.is.in.charge\", \"the snippet\")");   // returns the old value
            for (String code : snippets) {
                for (SnippetEvent event : shell.eval(code)) {
                    if (event.causeSnippet() != null) continue;    // only the snippet itself, not its dependents
                    System.out.printf("%-54s %-8s %s%n", code, event.status(), describe(shell, event));
                }
            }
        }
        System.out.println("host sees who.is.in.charge = " + System.getProperty("who.is.in.charge"));
    }

    static String describe(JShell shell, SnippetEvent event) {
        if (event.exception() instanceof EvalException e) {
            return "threw " + e.getExceptionClassName() + ": " + e.getMessage();
        }
        if (event.status() == Snippet.Status.REJECTED) {
            return shell.diagnostics(event.snippet())
                    .map(d -> d.getMessage(Locale.ROOT))
                    .collect(Collectors.joining("; "));
        }
        return event.value() == null ? "(declared)" : "= " + event.value();
    }
}
```

Output:

```text output
javac wrote [Formula, Formula$Unused]
f(3) = 7.0, class Formula, loader MemoryClassLoader
root of f: 1.414213562373
rejected: line 5, column 20: illegal start of expression
int answer = 6 * 7;                                    VALID    = 42
String greet(String name) { return "Hello, " + name; } VALID    (declared)
greet("Duke")                                          VALID    = "Hello, Duke"
Math.sqrt(2) * Math.sqrt(2)                            VALID    = 2.0000000000000004
answer = "forty-two";                                  REJECTED incompatible types: java.lang.String cannot be converted to int
Integer.parseInt("forty-two")                          VALID    threw java.lang.NumberFormatException: For input string: "forty-two"
System.setProperty("who.is.in.charge", "the snippet")  VALID    = null
host sees who.is.in.charge = the snippet
```

## How it works

* **Sources and class files are just objects.** javac never touches the disk here. It asks the file manager for the `.java` content, and it calls `getJavaFileForOutput` once per class it emits. One source produced two class files, `Formula` and `Formula$Unused`, because nested classes are separate classes in the JVM. The `TreeMap` keeps them in a stable order.
* **The class loader is the bridge.** `MemoryClassLoader` delegates to its parent first and only calls `defineClass` for names it holds. `Formula` therefore gets the JDK's `DoubleUnaryOperator` from the parent, which is why the cast in `formula(...)` works. The output confirms the class lives in `MemoryClassLoader`.
* **Generated code is real code.** `f.applyAsDouble` is an interface call on an ordinary class, so the JIT can inline and compile it like anything you wrote by hand. Newton's method converged to the square root of 2 in five steps.
* **Diagnostics are data.** A `DiagnosticCollector` gathers errors with line, column and message. Note that the error points at line 5 of the *generated* source. If users type the formula, translate positions back to their input before showing them. `Locale.ROOT` keeps the messages in English regardless of the machine.
* **JShell wraps snippets for you.** Each snippet becomes a synthetic class behind the scenes. `answer` survives between calls, `greet` is declared and then called, a type error is `REJECTED` with javac's own message, and a runtime exception comes back as an `EvalException` that carries the original class name instead of propagating into your code. A snippet that changes something others depend on also reports events for those dependents; filtering on `causeSnippet() == null` keeps only the direct result.
* **`value()` is a source representation.** `"Hello, Duke"` comes back with its quotes, and `Math.sqrt(2) * Math.sqrt(2)` shows its honest `2.0000000000000004`. You get strings, not objects. That is by design, because the default engine runs in another JVM.
* **The last line is the security bill.** With the `local` engine, snippets run inside your JVM, with your permissions. One innocent-looking call changed a system property that the host then read back. It could just as well have read your files, opened sockets or called `System.exit`.

The APIs are from Java 6 (`javax.tools`) and Java 9 (`jdk.jshell`). The example uses a text block and pattern matching for `instanceof`, hence Java 16.

## Gotchas

* **No compiler on a JRE.** `getSystemJavaCompiler()` returns `null` when the `jdk.compiler` module is missing, as in a `jlink` image without it or a JRE-only container. JShell needs `jdk.jshell` (and `jdk.jdi` for the default engine). Fail fast with a clear message at startup.
* **There is no sandbox anymore.** The Security Manager was deprecated in Java 17 (JEP 411) and permanently disabled in Java 24 (JEP 486). Nothing inside one JVM can stop compiled code from doing what your process may do. Untrusted code belongs in a separate process, container or VM, with resource limits, and with a kill switch.
* **The default JShell engine is a separate JVM, not a security boundary.** `JShell.create()` launches a remote JVM controlled over JDI. That protects you from `System.exit` and infinite loops (you can `stop()` or kill it), but it still runs as your user, and every value crosses a process boundary as a string. `local` skips the second JVM and runs snippets in your own, so a hung snippet hangs you.
* **The compiled code sees what javac sees.** javac resolves types against the class path you pass in its options (by default, the process's class path). To let generated code implement *your* interfaces, those class files must be on that path, and the loader's parent must see the same classes. Otherwise you get two different interfaces with the same name and a `ClassCastException`.
* **Each compilation costs.** javac is fast for a compiler but slow for a function call: expect milliseconds per compilation when warm and far more when cold. Every class loader with its classes stays in Metaspace until it is unreachable. Cache compiled results by source text, and drop the loader when you drop the formula.
* **Expression injection is code injection.** `formula("0; } static { System.exit(1); } public double unused(double x) { return 0")` is perfectly legal Java. String templating plus a compiler is `eval`. Validate input against a whitelist grammar before it gets anywhere near javac.

## When to use it (and when not to)

Runtime compilation shines for tools: test generators, code playgrounds, build plugins, annotation-processing tests, and benchmarks that specialize code for data known only at runtime. For trusted input (configuration written by your own team, generated code), it is a legitimate way to get JIT-speed custom logic without writing an interpreter.

For end-user input, think hard. A formula language with its own small parser (see [028](../03-build-it-yourself/028-parser-combinators.md)) is far easier to secure than "Java, but please be nice". If you must run user Java, do it in a separate, locked-down process. And if all you need is to generate a class, not compile Java source, the [Class-File API](088-classfile-api-hidden-classes.md) skips javac entirely.

## Related

* [088 · Generating Bytecode with the Class-File API](088-classfile-api-hidden-classes.md), runtime classes without a compiler in the loop
* [045 · Java as a Scripting Language](../05-modern-language/045-java-scripting.md), the source launcher that runs javac in memory for you
* [028 · Parser Combinators: Grammars as Code](../03-build-it-yourself/028-parser-combinators.md), the safer way to evaluate user formulas
* [085 · Dynamic Proxies: Implementing Interfaces at Runtime](085-dynamic-proxies.md), when you only need a runtime implementation of an interface

## Sources

* [`javax.tools.JavaCompiler` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.compiler/javax/tools/JavaCompiler.html), whose examples include a source file read from a String and a forwarding file manager
* [`jdk.jshell.JShell` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/jdk.jshell/jdk/jshell/JShell.html)
* [JEP 222: jshell: The Java Shell (Read-Eval-Print Loop)](https://openjdk.org/jeps/222)
* [JEP 486: Permanently Disable the Security Manager](https://openjdk.org/jeps/486)
