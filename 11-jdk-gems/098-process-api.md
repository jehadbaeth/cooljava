# 098 · The Process API: Pipelines and Process Handles

> Before Java 9, running `a | b | c` from Java meant a shell string or three threads shovelling bytes. `ProcessBuilder.startPipeline` wires the processes together for you, and `ProcessHandle` finally lets you ask who is alive, who the parent is and when something exits.

**Since:** Java 17 · **Category:** [JDK Gems](../README.md#jdk-gems) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

Calling another program from Java is easy until the second day:

* You want a pipe (`sort | uniq -c`), and `ProcessBuilder` does not use a shell. A `|` in an argument is just a character, and `Runtime.exec(String)` (deprecated since Java 18) merely splits the string on whitespace.
* You wrote `sh -c "..."` to get pipes and now an unvalidated filename is a command injection.
* You read stdout, but the child fills its stderr buffer first and both sides wait for each other forever.
* You need to know when it ends, so you poll `isAlive()` in a loop on a thread.
* You have a `Process`, but no way to ask for its pid, its start time or its parent. (The pid used to require reflection or a native library.)

## The trick

Java 9 added two things, and Java 17 added a convenience layer:

* **`ProcessBuilder.startPipeline(List<ProcessBuilder>)`** starts all processes and links each one's standard output to the next one's standard input. The JVM never sees the bytes in between: the streams of the intermediate processes are null streams. You read from the last process and, if you want, write into the first.
* **`ProcessHandle`** is a handle on any operating system process: `pid()`, `info()` (command, start time, CPU time), `parent()`, `children()`, `descendants()`, `isAlive()`, `destroy()` and `onExit()`. `Process.toHandle()` converts, `ProcessHandle.current()` is the JVM itself.
* **`Process.onExit()`** returns a `CompletableFuture<Process>` that completes when the process ends, so you compose it instead of polling.
* **Java 17** added `Process.inputReader()`, `errorReader()` and `outputWriter()`: a `BufferedReader` for stdout, one for stderr and a `BufferedWriter` for stdin, using the platform's native encoding. No more `new BufferedReader(new InputStreamReader(...))`.

This page uses only `echo`, `tr`, `sort`, `uniq` and `wc`, which exist on macOS and Linux. Windows has its own tools, so the commands (not the API) would change there.

## Full example

The program runs a five stage pipeline, feeds a pipeline from Java, inspects handles, kills a stuck child and exercises the redirects. It sets `LC_ALL=C` on every child so `sort` orders the same way everywhere, and squeezes whitespace because `uniq -c` and `wc` pad their numbers differently on macOS and Linux.

```java run
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;

public class ProcessTricks {

    static ProcessBuilder cmd(String... command) {
        ProcessBuilder builder = new ProcessBuilder(command);
        builder.environment().put("LC_ALL", "C");
        return builder;
    }

    static String tidy(String line) {
        return line.trim().replaceAll("\\s+", " ");
    }

    static void show(String label, Object value) {
        System.out.printf("%-34s %s%n", label, value);
    }

    public static void main(String[] args) throws Exception {
        System.out.println("== A pipeline without a shell");
        List<Process> pipeline = ProcessBuilder.startPipeline(List.of(
                cmd("echo", "banana apple banana cherry apple banana"),
                cmd("tr", " ", "\n"),
                cmd("sort"),
                cmd("uniq", "-c"),
                cmd("sort", "-rn")));
        Process last = pipeline.get(pipeline.size() - 1);
        try (BufferedReader out = last.inputReader()) {
            out.lines().map(ProcessTricks::tidy).forEach(line -> System.out.println("  " + line));
        }
        CompletableFuture.allOf(pipeline.stream().map(Process::onExit).toArray(CompletableFuture[]::new))
                .get(5, TimeUnit.SECONDS);
        show("exit codes", pipeline.stream().map(Process::exitValue).toList());

        List<Process> counter = ProcessBuilder.startPipeline(List.of(cmd("sort", "-u"), cmd("wc", "-l")));
        try (BufferedWriter stdin = counter.get(0).outputWriter()) {      // closing it ends sort's input
            for (String word : List.of("pear", "fig", "pear", "apple", "fig")) stdin.write(word + "\n");
        }
        try (BufferedReader out = counter.get(1).inputReader()) {
            show("distinct words, fed from Java", tidy(out.readLine()));
        }
        for (Process p : counter) p.waitFor();               // reaped now, so the child count below is exact
        try {
            ProcessBuilder.startPipeline(List.of(cmd("echo", "x"),
                    cmd("sort").redirectOutput(ProcessBuilder.Redirect.INHERIT), cmd("wc", "-l")));
        } catch (IllegalArgumentException e) {
            show("redirect in the middle", e.getMessage());
        }

        System.out.println("== Handles and onExit");
        ProcessHandle self = ProcessHandle.current();
        show("own pid is positive", self.pid() > 0);
        show("own start time is known", self.info().startInstant().isPresent());
        show("more than one process visible", ProcessHandle.allProcesses().count() > 1);
        Process sort = cmd("sort").start();                  // reads stdin until it is closed: a child we control
        ProcessHandle child = sort.toHandle();
        show("child is alive", child.isAlive());
        show("child's parent is this JVM", child.parent().map(p -> p.pid() == self.pid()).orElse(false));
        show("child's command", child.info().command().map(path -> Path.of(path).getFileName()).orElse(null));
        show("children of this JVM right now", self.children().count());
        CompletableFuture<Integer> exitCode = sort.onExit().thenApply(Process::exitValue);
        show("exit future done?", exitCode.isDone());
        try (BufferedWriter stdin = sort.outputWriter()) {
            stdin.write("b\na\n");
        }
        show("exit code once stdin is closed", exitCode.get(5, TimeUnit.SECONDS));
        show("its output", sort.inputReader().lines().toList());

        Process stuck = cmd("sort").start();
        show("supports normal termination", stuck.supportsNormalTermination());
        stuck.destroy();
        show("exit value after destroy()", stuck.onExit().get(5, TimeUnit.SECONDS).exitValue());

        System.out.println("== Redirects");
        Path dir = Files.createTempDirectory("process-demo");
        try {
            Files.writeString(dir.resolve("words.txt"), "pear\nfig\napple\n");
            Path sorted = dir.resolve("sorted.txt");
            cmd("sort", "words.txt").directory(dir.toFile()).redirectOutput(sorted.toFile()).start().waitFor();
            cmd("echo", "zucchini").redirectOutput(ProcessBuilder.Redirect.appendTo(sorted.toFile())).start().waitFor();
            show("sorted.txt (write, then append)", Files.readAllLines(sorted));

            Process failing = cmd("sort", "missing.txt").directory(dir.toFile()).start();
            show("missing file: exit code non-zero", failing.waitFor() != 0);
            show("missing file: stderr has text", failing.errorReader().lines().count() > 0);
            Process merged = cmd("sort", "missing.txt").directory(dir.toFile()).redirectErrorStream(true).start();
            show("merged: stdout has the error", merged.inputReader().lines().count() > 0);
            Process discarded = cmd("sort", "missing.txt").directory(dir.toFile())
                    .redirectError(ProcessBuilder.Redirect.DISCARD).start();
            show("discarded: stderr bytes", discarded.getErrorStream().readAllBytes().length);

            System.out.println("inheritIO, the child writes to this console:");
            cmd("echo", "  hello from the child").inheritIO().start().waitFor();
        } finally {
            try (var files = Files.walk(dir)) {
                files.sorted(Comparator.reverseOrder()).forEach(p -> p.toFile().delete());
            }
        }
    }
}
```

Output:

```text output
== A pipeline without a shell
  3 banana
  2 apple
  1 cherry
exit codes                         [0, 0, 0, 0, 0]
distinct words, fed from Java      3
redirect in the middle             builder redirectOutput() must be PIPE except for the last builder: INHERIT
== Handles and onExit
own pid is positive                true
own start time is known            true
more than one process visible      true
child is alive                     true
child's parent is this JVM         true
child's command                    sort
children of this JVM right now     1
exit future done?                  false
exit code once stdin is closed     0
its output                         [a, b]
supports normal termination        true
exit value after destroy()         143
== Redirects
sorted.txt (write, then append)    [apple, fig, pear, zucchini]
missing file: exit code non-zero   true
missing file: stderr has text      true
merged: stdout has the error       true
discarded: stderr bytes            0
inheritIO, the child writes to this console:
  hello from the child
```

## How it works

**The pipeline.** `startPipeline` validates all builders, starts the processes in order and links each one's stdout to the next one's stdin. The first output block is the classic word count: `echo` emits one line, `tr` turns the spaces into newlines, `sort` groups equal words, `uniq -c` counts the groups and `sort -rn` orders them by count, largest first. The counts are 3, 2 and 1 on purpose, so the order does not depend on how a particular `sort` breaks ties. `CompletableFuture.allOf` over the five `onExit()` futures waits for the whole pipeline, and all five exit codes are `0`.

**Feeding the first stage.** `outputWriter()` is the *stdin* of the process: you write to the output stream of the `Process` object because it is the process's input. Closing the writer sends end-of-file, which is what lets `sort -u` finish and pass its result to `wc -l`. Five words, three distinct, so the answer is `3`. Forget to close it and both processes wait forever: the most common way to hang a pipeline.

**The rules.** Only the first builder may redirect stdin and only the last may redirect stdout. Every other redirect must stay `PIPE`, because the JDK needs those two ends for the links, and the message in the output is the exception you get when you try anyway. Between the stages, the streams are null streams: calling `getInputStream()` on the second process gives you nothing, because the bytes never pass through Java.

**Handles.** `ProcessHandle.current()` describes the JVM, and `info()` offers the command, arguments, start instant, CPU time and user, each as an `Optional` because the operating system may refuse to tell you. Pids and start times differ on every run, so the program prints facts about them (positive, known, present) rather than the numbers. `sort` with an open stdin is a convenient child to experiment with: it stays alive until you close the pipe. Its handle says the parent is this JVM and the command is `sort`, and `children()` finds exactly one child because the earlier pipelines were already reaped (that is why the program waits on them). `descendants()` adds grandchildren, and `ProcessHandle.allProcesses()` is a snapshot of everything you are allowed to see.

**onExit.** `sort.onExit()` returns a `CompletableFuture<Process>`. The example maps it to the exit code, shows it is not done while stdin is open, and reads `0` after the writer is closed. The reaper thread completes the future, so `thenApply`, `allOf` and `orTimeout` work as for any other future (see [080](../09-concurrency/080-completablefuture-cookbook.md)). Cancelling the future does not affect the process.

**Killing.** `destroy()` asks politely: on Unix it sends `SIGTERM`, and `supportsNormalTermination()` says `true` there. The exit value `143` is `128 + 15`, the shell convention for "killed by signal 15". `destroyForcibly()` sends `SIGKILL`, which shows up as `137`.

**Redirects.** `directory(...)` sets the working directory, which is why `sort words.txt` finds its file. `redirectOutput(File)` writes (truncating) and `Redirect.appendTo` appends, so `sorted.txt` ends up with the sorted words and then `zucchini`. For the failing `sort missing.txt` the program only checks that the exit code is non-zero and that stderr has text, because the wording of the message differs between macOS and Linux. `redirectErrorStream(true)` merges stderr into stdout, so one reader sees everything, and `Redirect.DISCARD` throws stderr away (zero bytes). `inheritIO()` hands the child your own stdin, stdout and stderr: the last line of the output was written by the child process directly to the console.

## Gotchas

* **Unread output deadlocks.** A pipe has a limited buffer (often 64 KB). If a child writes more than that to a stream you are not reading, it blocks, and your `waitFor()` blocks with it. Drain stdout and stderr, or merge them with `redirectErrorStream(true)`, or send them to a file, `DISCARD` or `INHERIT`. With two streams to read at once, give each its own (virtual) thread.
* **There is no shell.** `new ProcessBuilder("echo", "$HOME")` prints the text `$HOME`. No globbing, no `~`, no pipes, no quotes: each list element is one argument. That is a feature, because it makes injection hard. If you do need `sh -c`, pass user data as separate arguments (`sh -c 'sort "$1"' sh userFile`), never glued into the script string.
* **`destroy()` kills one process.** Its children keep running. Use `handle.descendants().forEach(ProcessHandle::destroy)` first if you started a tree. The same applies when the JVM exits: nothing kills the children for you, and dropping the last reference to a `Process` does not kill it either.
* **Never wait without a limit.** Prefer `waitFor(timeout, unit)` and call `destroyForcibly()` when it returns `false`.
* **Pids are recycled, and status is a snapshot.** A pid you stored an hour ago may name a different process now, and a process can end between your `isAlive()` check and your next call. The Javadoc says outright to avoid assumptions about liveness or identity. Treat `isAlive()` as a hint, not a lock.
* **`onExit()` on someone else's process has no exit code.** `ProcessHandle.of(pid).get().onExit()` completes with a `ProcessHandle`, which has no exit status at all. Only the `Process` objects of your own children give you `exitValue()`. Calling `onExit()` on the current JVM's handle throws `IllegalStateException`.
* **Tools differ between systems.** The program squeezes whitespace and sets `LC_ALL=C` because `uniq -c` and `sort` do not behave identically on every platform. Windows has none of these commands. A Java program that shells out is only as portable as the tools it calls.
* **Do not run a process for what the JDK can do.** `sort | uniq -c` is a demonstration. In real code it is a `Collectors.groupingBy` with `counting()`.

## When to use it (and when not to)

Use `ProcessBuilder` to glue Java to tools that already do the job: `git`, `ffmpeg`, `openssl`, a build tool, a database dump. Use `startPipeline` when the data should flow between the programs without passing through your heap. Use `ProcessHandle` for supervision: a watchdog that waits for a worker to exit, a launcher that cleans up its descendants, a health check that asks whether the pid in a lock file is still alive.

Do not use it where a library exists in Java, where the same command line does not exist on the platforms you ship to, or where the arguments come from users and could be steered at an option (`-rf`) instead of a value. For long-lived, chatty children (language servers, REPLs), plan the I/O up front: one thread per stream, or virtual threads (see [077](../09-concurrency/077-virtual-threads.md)).

## Related

* [077 · Virtual Threads: A Million Threads and the Pinning Trap](../09-concurrency/077-virtual-threads.md), for reading child output without tying up a platform thread
* [080 · CompletableFuture Cookbook](../09-concurrency/080-completablefuture-cookbook.md), for composing `onExit()` futures
* [045 · Java as a Scripting Language](../05-modern-language/045-java-scripting.md), where a process pipeline is the natural glue code
* [048 · Try-With-Resources Tricks](../05-modern-language/048-try-with-resources-tricks.md), for closing the streams of a process

## Sources

* [`ProcessBuilder` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/ProcessBuilder.html), including `startPipeline` and `Redirect`
* [`ProcessHandle` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/ProcessHandle.html)
* [`Process` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/Process.html), for `onExit`, `inputReader`, `errorReader` and `outputWriter`
* [JEP 102: Process API Updates](https://openjdk.org/jeps/102)
