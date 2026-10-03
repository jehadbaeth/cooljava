# 089 · Calling C Without JNI: The Foreign Function and Memory API

> No header files, no `javah`, no glue library to compile for every platform. A C function becomes a `MethodHandle`, a C struct becomes a `MemoryLayout`, and `qsort` happily calls a Java comparator.

**Since:** Java 22 · **Category:** [JVM, Reflection and Performance](../README.md#jvm-reflection-and-performance) · **Level:** Advanced · **Verdict:** ✅ Production

## The problem

For 25 years, calling a C function from Java meant JNI. You declared a `native` method, generated a header, wrote a C file that unpacked `jstring`s and `jobject`s, compiled it once per operating system and CPU, shipped the `.so`, `.dylib` and `.dll`, and prayed that nobody got a local reference wrong. All that to call `strlen`.

Off-heap memory had its own folklore: `ByteBuffer.allocateDirect` (2 GB limit, freed whenever the GC feels like it) or `sun.misc.Unsafe` (fast, unsupported, and one wrong offset away from a segfault).

## The trick

Project Panama replaced both with one pure Java API in `java.lang.foreign`, final since JDK 22 (JEP 454). Four pieces do all the work:

* **`Linker`** turns a native function address plus a `FunctionDescriptor` (the C signature, spelled in layouts) into a `MethodHandle`. That is a *downcall*. It can also wrap a Java method handle in a C function pointer, an *upcall*.
* **`SymbolLookup`** finds functions by name. `Linker.nativeLinker().defaultLookup()` already knows the C standard library.
* **`Arena`** owns native memory and frees it deterministically when closed. `try`-with-resources is the whole memory management story.
* **`MemorySegment`** and **`MemoryLayout`** are bounds-checked views of that memory, with named struct fields instead of hand-computed offsets.

```java
MethodHandle strlen = linker.downcallHandle(
        linker.defaultLookup().find("strlen").orElseThrow(),
        FunctionDescriptor.of(JAVA_LONG, ADDRESS));          // size_t strlen(const char *)

try (Arena arena = Arena.ofConfined()) {
    long n = (long) strlen.invokeExact(arena.allocateFrom("Hello, Panama!"));
}                                                         // the C string is freed here
```

No C compiler was harmed. The JVM generates the calling-convention glue at runtime.

## Full example

The program calls three libc functions that exist on macOS and Linux: `strlen`, `qsort` (with a Java comparator as the callback) and `gmtime_r` (which fills in a real C struct). Then it shows the safety nets: padding rules, bounds checks and lifetime checks. Run it with `--enable-native-access=ALL-UNNAMED`.

```java run args="--enable-native-access=ALL-UNNAMED"
import java.lang.foreign.*;
import java.lang.foreign.MemoryLayout.PathElement;
import java.lang.invoke.*;
import java.time.Instant;
import java.util.*;

import static java.lang.foreign.ValueLayout.*;

public class PanamaDemo {

    static final Linker LINKER = Linker.nativeLinker();
    static final SymbolLookup LIBC = LINKER.defaultLookup();

    static MethodHandle downcall(String name, FunctionDescriptor descriptor) {
        MemorySegment address = LIBC.find(name).orElseThrow(() -> new UnsatisfiedLinkError(name));
        return LINKER.downcallHandle(address, descriptor);
    }

    // size_t strlen(const char *s);
    static final MethodHandle STRLEN = downcall("strlen", FunctionDescriptor.of(JAVA_LONG, ADDRESS));

    // void qsort(void *base, size_t count, size_t size, int (*compar)(const void *, const void *));
    static final MethodHandle QSORT = downcall("qsort",
            FunctionDescriptor.ofVoid(ADDRESS, JAVA_LONG, JAVA_LONG, ADDRESS));

    // struct tm *gmtime_r(const time_t *clock, struct tm *result);
    static final MethodHandle GMTIME_R = downcall("gmtime_r", FunctionDescriptor.of(ADDRESS, ADDRESS, ADDRESS));

    // struct point { int x; int y; };
    static final StructLayout POINT = MemoryLayout.structLayout(JAVA_INT.withName("x"), JAVA_INT.withName("y"));
    static final VarHandle X = POINT.varHandle(PathElement.groupElement("x"));
    static final VarHandle Y = POINT.varHandle(PathElement.groupElement("y"));

    // struct tm on 64-bit macOS and Linux: nine ints, 4 bytes of padding, a long and a char pointer.
    static final StructLayout TM = MemoryLayout.structLayout(
            JAVA_INT.withName("tm_sec"), JAVA_INT.withName("tm_min"), JAVA_INT.withName("tm_hour"),
            JAVA_INT.withName("tm_mday"), JAVA_INT.withName("tm_mon"), JAVA_INT.withName("tm_year"),
            JAVA_INT.withName("tm_wday"), JAVA_INT.withName("tm_yday"), JAVA_INT.withName("tm_isdst"),
            MemoryLayout.paddingLayout(4),
            JAVA_LONG.withName("tm_gmtoff"),
            ADDRESS.withName("tm_zone"));

    /** The callback qsort calls: int compar(const void *a, const void *b). Sorts by x, then y. */
    static int comparePoints(MemorySegment a, MemorySegment b) {
        int byX = Integer.compare((int) X.get(a, 0L), (int) X.get(b, 0L));
        return byX != 0 ? byX : Integer.compare((int) Y.get(a, 0L), (int) Y.get(b, 0L));
    }

    static int tm(MemorySegment tm, String field) {
        return tm.get(JAVA_INT, TM.byteOffset(PathElement.groupElement(field)));
    }

    // Keeps the output ASCII: non-ASCII characters are printed as Java escapes.
    static String escape(String s) {
        var sb = new StringBuilder();
        s.chars().forEach(c -> sb.append(c < 128 ? String.valueOf((char) c) : String.format("\\u%04x", c)));
        return sb.toString();
    }

    public static void main(String[] args) throws Throwable {
        MemorySegment escaped;
        try (Arena arena = Arena.ofConfined()) {
            // 1. Strings: allocateFrom writes a NUL-terminated UTF-8 copy into native memory.
            for (String s : List.of("Hello, Panama!", "naïve")) {
                long length = (long) STRLEN.invokeExact(arena.allocateFrom(s));
                System.out.printf("strlen(\"%s\") = %d bytes, String.length() = %d chars%n",
                        escape(s), length, s.length());
            }

            // 2. Structs plus an upcall: C's qsort sorts native structs with a Java comparator.
            int[][] input = {{5, 0}, {2, 7}, {8, 8}, {1, 9}, {2, 3}};
            MemorySegment points = arena.allocate(POINT, input.length);
            for (int i = 0; i < input.length; i++) {
                MemorySegment p = points.asSlice(i * POINT.byteSize(), POINT);
                X.set(p, 0L, input[i][0]);
                Y.set(p, 0L, input[i][1]);
            }
            MethodHandle compare = MethodHandles.lookup().findStatic(PanamaDemo.class, "comparePoints",
                    MethodType.methodType(int.class, MemorySegment.class, MemorySegment.class));
            AddressLayout pointPtr = ADDRESS.withTargetLayout(POINT);   // "this pointer points at a point"
            MemorySegment comparator = LINKER.upcallStub(compare,
                    FunctionDescriptor.of(JAVA_INT, pointPtr, pointPtr), arena);
            QSORT.invokeExact(points, (long) input.length, POINT.byteSize(), comparator);
            StringJoiner sorted = new StringJoiner(", ", "[", "]");
            for (int i = 0; i < input.length; i++) {
                MemorySegment p = points.asSlice(i * POINT.byteSize(), POINT);
                sorted.add("(" + (int) X.get(p, 0L) + ", " + (int) Y.get(p, 0L) + ")");
            }
            System.out.println("sorted by C:   " + sorted);

            // 3. A real C struct filled in by libc, padding and all.
            System.out.println("struct tm:     " + TM.byteSize() + " bytes, tm_gmtoff at offset "
                    + TM.byteOffset(PathElement.groupElement("tm_gmtoff")));
            long epochSeconds = 1_000_000_000L;
            MemorySegment tm = arena.allocate(TM);
            MemorySegment result = (MemorySegment) GMTIME_R.invokeExact(
                    arena.allocateFrom(JAVA_LONG, epochSeconds), tm);
            System.out.printf("gmtime_r:      %d-%02d-%02d %02d:%02d:%02d, weekday %d, day of year %d, same struct? %b%n",
                    tm(tm, "tm_year") + 1900, tm(tm, "tm_mon") + 1, tm(tm, "tm_mday"),
                    tm(tm, "tm_hour"), tm(tm, "tm_min"), tm(tm, "tm_sec"),
                    tm(tm, "tm_wday"), tm(tm, "tm_yday"), result.address() == tm.address());
            System.out.println("java.time:     " + Instant.ofEpochSecond(epochSeconds));

            // 4. Padding is your job: structLayout never inserts it, it refuses misaligned fields.
            try {
                MemoryLayout.structLayout(JAVA_INT.withName("tm_isdst"), JAVA_LONG.withName("tm_gmtoff"));
            } catch (IllegalArgumentException e) {
                System.out.println("no padding:    " + e.getMessage());
            }
            StructLayout scored = MemoryLayout.structLayout(JAVA_LONG.withName("id"), JAVA_INT.withName("score"));
            try {
                arena.allocate(scored, 3);
            } catch (IllegalArgumentException e) {
                System.out.println("array of " + scored + ": " + e.getMessage());
            }
            StructLayout padded = MemoryLayout.structLayout(
                    JAVA_LONG.withName("id"), JAVA_INT.withName("score"), MemoryLayout.paddingLayout(4));
            System.out.println("array of " + padded + ": " + arena.allocate(padded, 3).byteSize() + " bytes");

            // 5. Bounds are checked: one int past the end is an exception, not a corrupted heap.
            try {
                points.get(JAVA_INT, points.byteSize());
            } catch (IndexOutOfBoundsException e) {
                System.out.println("out of bounds: " + e.getClass().getSimpleName());
            }
            escaped = points;
        }
        // 6. Lifetimes are checked: the arena is closed, so the memory is gone.
        try {
            escaped.get(JAVA_INT, 0);
        } catch (IllegalStateException e) {
            System.out.println("after close:   " + e.getMessage());
        }
    }
}
```

Output:

```text output
strlen("Hello, Panama!") = 14 bytes, String.length() = 14 chars
strlen("na\u00efve") = 6 bytes, String.length() = 5 chars
sorted by C:   [(1, 9), (2, 3), (2, 7), (5, 0), (8, 8)]
struct tm:     56 bytes, tm_gmtoff at offset 40
gmtime_r:      2001-09-09 01:46:40, weekday 0, day of year 251, same struct? true
java.time:     2001-09-09T01:46:40Z
no padding:    Invalid alignment constraint for member layout: j8(tm_gmtoff)
array of [j8(id)i4(score)]: Element layout size is not multiple of alignment
array of [j8(id)i4(score)x4]: 48 bytes
out of bounds: IndexOutOfBoundsException
after close:   Already closed
```

## How it works

* **A downcall is a method handle with a C calling convention.** `FunctionDescriptor.of(JAVA_LONG, ADDRESS)` says "returns a 64-bit integer, takes one pointer". The linker generates the stub that moves Java arguments into the registers the platform ABI expects (arm64 AAPCS here, System V on x86-64 Linux). Because the result is a `MethodHandle`, `invokeExact` rules apply: the casts `(long)` and `(MemorySegment)` are part of the call signature, exactly as in [086](086-methodhandles-lambdametafactory.md).
* **Strings are bytes.** `arena.allocateFrom("naïve")` encodes UTF-8 and appends a NUL, so C sees 6 bytes for 5 Java chars. The output shows both numbers side by side. `MemorySegment.getString(0)` goes the other way.
* **Upcalls turn Java into a C function pointer.** `upcallStub` wraps `comparePoints` in a real native function and returns its address. `qsort` calls it like any C comparator, and the five points come back sorted by x, then y. The stub lives as long as the arena passed to it.
* **Pointers from C have no size.** When native code hands you an address, the JVM cannot know how much memory sits behind it, so it gives you a zero-length segment. `ADDRESS.withTargetLayout(POINT)` declares "these point at a `point`", which makes the incoming segments 8 bytes long and readable. Without it, the first `X.get` in the comparator throws `IndexOutOfBoundsException` inside the upcall (see Gotchas for why that is fatal).
* **Layouts replace offset arithmetic.** `TM.byteOffset(groupElement("tm_gmtoff"))` computes 40, and the struct is 56 bytes: nine 4-byte ints end at offset 36, then 4 bytes of padding put the `long` on an 8-byte boundary, then the 8-byte pointer. `gmtime_r` filled that struct, and the date matches `java.time` for the same instant, which is good evidence the layout is right. The `VarHandle`s from `varHandle(...)` take the segment plus a base offset (`0L`) as coordinates, so `X.get(p, 0L)` reads field `x` of the point that starts at `p`.
* **Padding is explicit, and the API checks your work.** `structLayout` does not insert padding the way a C compiler does. It refuses a member that would land misaligned (`Invalid alignment constraint for member layout: j8(tm_gmtoff)`). It also accepts a struct whose size is not a multiple of its alignment, `[j8(id)i4(score)]` at 12 bytes, but refuses to make an array of it, because element two would start misaligned. Adding the 4 bytes of trailing padding that a C compiler would add fixes it: 3 elements, 48 bytes.
* **Memory safety is the headline feature.** Reading one `int` past the end of the 40-byte points array throws instead of reading a neighbor's memory, and touching the segment after its arena closed throws `IllegalStateException: Already closed` instead of a use-after-free. A confined arena is also checked for the owning thread.

## Gotchas

* **Restricted methods need permission.** `downcallHandle`, `upcallStub`, `withTargetLayout`, `MemorySegment.reinterpret` and `SymbolLookup.libraryLookup` can crash the JVM if you lie to them, so they are *restricted*. On JDK 25, calling one without `--enable-native-access=ALL-UNNAMED` (or `=your.module`, or `Enable-Native-Access: ALL-UNNAMED` in an executable JAR's manifest) prints a warning, and the warning says that a future release will block the call. JNI gets the same treatment since JEP 472.
* **The descriptor is a promise the JVM cannot check.** Declare `strlen` as returning `JAVA_INT` or pass the wrong argument count and you get garbage or a crash, not an exception. The safety nets cover memory access through segments, not what C does with the pointers you hand it.
* **C types are platform dependent.** `long` and `size_t` are 64-bit on macOS and Linux, but `long` is 32-bit on Windows, which also has no `gmtime_r`. `Linker.nativeLinker().canonicalLayouts()` maps C type names to the right layouts for the current platform. For real libraries, let [jextract](https://github.com/openjdk/jextract) generate the layouts and handles from the header file instead of typing them.
* **An exception thrown inside an upcall is fatal.** There is no Java caller to propagate it to, so the JVM prints the stack trace and `Unrecoverable uncaught exception encountered. The VM will now exit`. Catch everything inside callbacks.
* **Arenas have rules.** `ofConfined` is single-threaded and the fastest. `ofShared` can be used and closed from any thread. `ofAuto` frees memory when the GC decides, like a direct buffer. `global` never frees. Never keep an upcall stub after its arena closes; C calling a freed stub crashes the process.

## When to use it (and when not to)

For any new native interop, this is the answer. It is final, supported, designed to be at least as fast as JNI, and it removes the C build from your project entirely. It is also the modern replacement for `sun.misc.Unsafe` off-heap tricks (now deprecated for removal), with memory-mapped files and huge off-heap buffers as first-class citizens.

Still, think twice before going native at all. Every downcall gives up the JVM's safety for whatever the C code does, and pure Java is usually fast enough. Use FFM for existing native libraries (codecs, crypto hardware, GPU runtimes, OS APIs), not to "speed up" code the JIT already compiles well. And for anything bigger than a handful of functions, generate the bindings with jextract rather than hand-writing descriptors.

## Related

* [086 · MethodHandles and LambdaMetafactory: Reflection at Full Speed](086-methodhandles-lambdametafactory.md), the handle type every downcall returns
* [093 · SIMD in Java with the Vector API (Incubator)](093-vector-api.md), which can load vectors straight from memory segments
* [048 · Try-With-Resources Tricks](../05-modern-language/048-try-with-resources-tricks.md), because an `Arena` is just an `AutoCloseable`
* [090 · Compile and Run Java at Runtime](090-runtime-compilation-jshell.md), the other way to bolt code onto a running JVM

## Sources

* [JEP 454: Foreign Function & Memory API](https://openjdk.org/jeps/454)
* [`java.lang.foreign.Linker` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/foreign/Linker.html)
* [`java.lang.foreign.MemoryLayout` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/foreign/MemoryLayout.html), including the note that `structLayout` never inserts padding
* [JEP 472: Prepare to Restrict the Use of JNI](https://openjdk.org/jeps/472)
* [jextract](https://github.com/openjdk/jextract), the binding generator
