# 099 · Zip Files as File Systems and Other NIO Gems

> Editing a zip with `ZipOutputStream` means streams, entries and a copy loop. Opening it as a `FileSystem` means `Files.writeString`, `Files.copy` and `Files.walk` on paths that happen to live inside the archive.

**Since:** Java 17 · **Category:** [JDK Gems](../README.md#jdk-gems) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

The classic zip API is a pair of streams. Reading means a `ZipFile`, an entry lookup and an `InputStream`. Changing *one* entry means copying every other entry from the old archive into a new `ZipOutputStream`, skipping or replacing the one you care about, then swapping files. Most of that code is plumbing, and none of it composes with the rest of `java.nio.file`: you cannot hand an archive entry to a method that takes a `Path`, and you cannot `Files.walk` a jar.

## The trick

The JDK ships a **zip file system provider** (module `jdk.zipfs`). It treats a zip or jar as a `FileSystem`, so every entry is a `Path` and every method of `Files` works on it:

```java
try (FileSystem fs = FileSystems.newFileSystem(zip, Map.of("create", "true"))) {
    Files.writeString(fs.getPath("/docs/readme.txt"), "Hello from inside a zip\n");
}
```

`create` makes the archive if it does not exist. Without it, the same call opens an existing one, and `Map.of("accessMode", "readOnly")` opens it read-only (writes then throw `ReadOnlyFileSystemException`). The `newFileSystem(Path, Map)` overload exists since Java 13. Before that you had to go through a `jar:` URI, which still works:

```java
URI uri = URI.create("jar:" + zip.toUri());                       // jar:file:///.../bundle.zip
try (FileSystem fs = FileSystems.newFileSystem(uri, Map.of("create", "true"))) { ... }
```

Because paths from a zip file system are ordinary `Path` objects, `Files.copy`, `Files.move`, `Files.mismatch` and friends work between the archive and the real disk without any glue code. The example below also walks through a few other small NIO conveniences you can use in the same program: `Files.readString` and `Files.writeString` (Java 11), `Files.mismatch` (Java 12), `Files.walk` in a try-with-resources, and a temp directory that cleans up after itself. The trick itself works on Java 13 and later. This example needs 17 only because it prints a magic number with `HexFormat`.

## Full example

Everything happens under `Files.createTempDirectory` and is deleted at the end. The listings are sorted, because `Files.walk` promises no order.

```java run
import java.io.IOException;
import java.io.UncheckedIOException;
import java.net.URI;
import java.nio.file.*;
import java.nio.file.spi.FileSystemProvider;
import java.util.*;
import java.util.stream.Stream;
import java.util.zip.ZipFile;

public class ZipFsDemo {

    public static void main(String[] args) throws IOException {
        Path dir = Files.createTempDirectory("zipfs-demo");           // everything lives here and is deleted at the end
        try {
            Path zip = dir.resolve("bundle.zip");

            // 1. "create" makes the archive. From here on, plain Files calls work on paths inside it.
            try (FileSystem fs = FileSystems.newFileSystem(zip, Map.of("create", "true"))) {
                Files.createDirectories(fs.getPath("/docs/guides"));
                Files.writeString(fs.getPath("/docs/readme.txt"), "Hello from inside a zip\n");
                Files.writeString(fs.getPath("/docs/guides/intro.txt"), "A zip file is a file system.\n");
                Files.write(fs.getPath("/data.bin"), new byte[] {1, 2, 3, 4});
                System.out.println("scheme: " + fs.provider().getScheme() + ", separator: " + fs.getSeparator());
            }
            System.out.println("created:      " + entryNames(zip));

            // 2. Edit: replace, move, delete, and copy in a file from the real disk. Nothing is written until close.
            Path notes = Files.writeString(dir.resolve("notes.txt"), "Edited on disk\n");
            try (FileSystem fs = FileSystems.newFileSystem(zip)) {
                Files.writeString(fs.getPath("/docs/readme.txt"), "Edited in zip\n");
                Files.move(fs.getPath("/data.bin"), fs.getPath("/docs/data.bin"));
                Files.delete(fs.getPath("/docs/guides/intro.txt"));
                Files.copy(notes, fs.getPath("/docs/notes.txt"));
                System.out.println("while open:   " + entryNames(zip) + "  (the file on disk has not changed yet)");
            }
            System.out.println("after close:  " + entryNames(zip));

            // 3. Read: walk the archive (sorted, and the stream is closed), then read and compare entries.
            Path leaked;
            try (FileSystem fs = FileSystems.newFileSystem(zip);
                 Stream<Path> walk = Files.walk(fs.getPath("/"))) {
                walk.sorted().forEach(p -> System.out.println("  " + p + (Files.isDirectory(p) ? "  (directory)" : "  " + size(p) + " bytes")));
                Path readme = fs.getPath("/docs/readme.txt");
                System.out.println("readString:   " + Files.readString(readme).strip());
                System.out.println("mismatch(zip notes, disk notes): " + Files.mismatch(fs.getPath("/docs/notes.txt"), notes));
                System.out.println("mismatch(zip readme, disk notes): " + Files.mismatch(readme, notes));
                try {
                    fs.getPath("/docs").resolve(notes.getFileName());           // a disk Path inside a zip Path
                } catch (ProviderMismatchException e) {
                    System.out.println("resolve(diskPath): ProviderMismatchException");
                }
                leaked = readme;
            }
            try {
                Files.exists(leaked);
            } catch (ClosedFileSystemException e) {
                System.out.println("path used after close: ClosedFileSystemException");
            }

            // 4. The zip provider is one of several. There is no in-memory one in the JDK (Jimfs is a library for that).
            System.out.println("providers: " + FileSystemProvider.installedProviders().stream().map(FileSystemProvider::getScheme).sorted().toList());
            Path object = FileSystems.getFileSystem(URI.create("jrt:/")).getPath("/modules/java.base/java/lang/Object.class");
            try (var in = Files.newInputStream(object)) {
                System.out.println("Object.class starts with " + HexFormat.of().withUpperCase().formatHex(in.readNBytes(4)));
            }
        } finally {
            deleteTree(dir);
        }
        System.out.println("temp dir exists after cleanup: " + Files.exists(dir));
    }

    static List<String> entryNames(Path zip) throws IOException {
        try (ZipFile file = new ZipFile(zip.toFile())) {
            return file.stream().map(entry -> entry.getName()).sorted().toList();
        }
    }

    static long size(Path path) {
        try {
            return Files.size(path);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    static void deleteTree(Path root) throws IOException {
        try (Stream<Path> walk = Files.walk(root)) {
            for (Path path : walk.sorted(Comparator.reverseOrder()).toList()) {     // children sort after their parents
                Files.delete(path);
            }
        }
    }
}
```

Output:

```text output
scheme: jar, separator: /
created:      [data.bin, docs/, docs/guides/, docs/guides/intro.txt, docs/readme.txt]
while open:   [data.bin, docs/, docs/guides/, docs/guides/intro.txt, docs/readme.txt]  (the file on disk has not changed yet)
after close:  [docs/, docs/data.bin, docs/guides/, docs/notes.txt, docs/readme.txt]
  /  (directory)
  /docs  (directory)
  /docs/data.bin  4 bytes
  /docs/guides  (directory)
  /docs/notes.txt  15 bytes
  /docs/readme.txt  14 bytes
readString:   Edited in zip
mismatch(zip notes, disk notes): -1
mismatch(zip readme, disk notes): 7
resolve(diskPath): ProviderMismatchException
path used after close: ClosedFileSystemException
providers: [file, jar, jrt]
Object.class starts with CAFEBABE
temp dir exists after cleanup: false
```

## How it works

* **A provider per scheme.** `FileSystems` finds file systems through `FileSystemProvider`s. The default file system is the `file` provider, the zip file system is the `jar` provider (the output shows `scheme: jar`), and `jrt` exposes the JDK's own runtime image. That is the last line of the demo: `Object.class` read as an ordinary `Path` from `jrt:/`, starting with the class-file magic number `CAFEBABE`. The `providers:` line shows these are the three the JDK ships. There is **no in-memory file system** among them. Google's [Jimfs](https://github.com/google/jimfs) is the usual library when tests need one, and a zip file system is the nearest built-in thing, but it is still backed by a file.
* **The archive is written on `close()`.** Inside the try block you are editing an in-memory index. The `while open` line shows that the file on disk still has the old entries after the replace, move, delete and copy. When the file system closes, `ZipFileSystem.close()` calls `sync()`, which writes a complete new archive into a temp file in the same directory and moves it over the original (this is how the JDK 25 source does it, not a documented guarantee). The `after close` line shows the result.
* **Entries are absolute paths.** `fs.getPath("/docs/readme.txt")` uses `/` as the separator, as the first output line shows. Directories are entries too: the `ZipFile` listing contains `docs/` and `docs/guides/`, which `Files.createDirectories` created for us, and `Files.walk` yields them as directories.
* **Cross-provider operations just work.** `Files.copy(notes, zipEntry)` copies from the disk into the archive, and `Files.mismatch(zipEntry, diskFile)` compares an entry with a real file without extracting anything. `mismatch` returns `-1` when the contents are identical and otherwise the position of the first differing byte: `Edited in zip` and `Edited on disk` share the prefix `Edited ` (7 bytes), so the answer is `7`.
* **`readString` and `writeString`** are one-liners for UTF-8 text. `writeString` uses the same defaults as `Files.write` (create, truncate, write), so writing to an existing entry replaces it, which is how the readme was edited in place.
* **The stream from `Files.walk` holds an open directory**, so it belongs in a try-with-resources, here together with the file system (resources close in reverse order: the walk first, then the file system). `Files.list`, `Files.find` and `Files.lines` work the same way.
* **Deleting a tree is a reverse sort.** In natural order a path sorts before everything below it, so `sorted(Comparator.reverseOrder())` visits children before parents, which is the order `Files.delete` needs. `Files.walkFileTree` with a visitor does the same job without sorting.

## Gotchas

* **Forgetting to close loses your changes.** Until `close()`, nothing is in the file. Always use try-with-resources.
* **Close rewrites the whole archive.** If something changed, `sync()` writes every entry again. One session with many edits is cheap, a loop that opens, edits and closes the same large jar for each entry is not.
* **Paths belong to their file system.** Mixing them throws `ProviderMismatchException`. The classic mistake is `zipDir.resolve(diskFile.getFileName())`, because `getFileName()` returns a disk `Path`. Convert it first: `zipDir.resolve(diskFile.getFileName().toString())`. And a zip path cannot outlive its file system: after `close()`, any use throws `ClosedFileSystemException`, as the demo shows.
* **Opening reads the whole table of contents.** The provider loads the archive's central directory into memory when it opens (`initCEN` in the JDK source). For a huge archive that you only need to scan once, `ZipFile` or `ZipInputStream` is lighter.
* **Not everything is supported.** The module documentation says the provider cannot open an archive that contains entries with `.` or `..` in their names. And do not open the same archive twice and edit through both file systems: each one rewrites the whole file on close, so the last one to close wins.
* **Order is not defined.** `Files.walk` and `Files.list` return entries in whatever order the file system has them. Sort before printing, comparing or testing.
* **Temp directories are yours to clean up.** `Files.createTempDirectory` never deletes anything for you, not even on JVM exit. Put the cleanup in a `finally` block, as the example does.

## When to use it (and when not to)

Use it whenever code needs to *look inside* or *modify* an archive: patching a config file in a jar, assembling test fixtures, packaging build output, or listing the resources that sit inside your own jar (open the jar as a file system and `Files.walk` it, which is the classic "list resources in a jar" problem solved in three lines). It also makes archive-related code easy to test, because the same code works on a directory and on a zip.

Do not use it for streaming. Producing a zip on the fly into an HTTP response, reading one from a socket, or processing a multi-gigabyte archive entry by entry is a job for `ZipOutputStream` and `ZipInputStream`. And since the whole archive is rewritten on close, a zip file system is the wrong tool for something that updates one entry many times a second.

## Related

* [048 · Try-With-Resources Tricks](../05-modern-language/048-try-with-resources-tricks.md), for the closing order of several resources at once
* [088 · Generating Bytecode with the Class-File API](../10-jvm-performance/088-classfile-api-hidden-classes.md), for what to do with the `.class` bytes once you can read them
* [098 · The Process API: Pipelines and Process Handles](098-process-api.md), another everyday JDK API with sharp edges

## Sources

* [Module `jdk.zipfs`](https://docs.oracle.com/en/java/javase/25/docs/api/jdk.zipfs/module-summary.html), the documentation of the zip file system provider and its properties
* [`FileSystems`](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/nio/file/FileSystems.html) and [`Files`](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/nio/file/Files.html) in the Java 25 API docs
* [Zip File System Provider](https://docs.oracle.com/javase/8/docs/technotes/guides/io/fsp/zipfilesystemprovider.html), the original Java 7 era guide with the `jar:` URI form
* [Jimfs](https://github.com/google/jimfs), Google's in-memory file system for Java
