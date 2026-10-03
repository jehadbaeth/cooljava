# 093 · SIMD in Java with the Vector API (Incubator)

> One CPU instruction, several numbers at a time. The Vector API lets you write that explicitly, and it has been "almost ready" since Java 16 because it is waiting for Project Valhalla.

**Since:** Java 16 (incubator, JEP 338) · **Category:** [JVM, Reflection and Performance](../README.md#jvm-reflection-and-performance) · **Level:** Advanced · **Verdict:** ⚠️ Situational

## The problem

A scalar loop does one addition per instruction. Your CPU has registers 128, 256 or 512 bits wide and can add four, eight or sixteen floats in the same time. That is SIMD (single instruction, multiple data), and for number crunching it is where the next 4x lives.

HotSpot already tries to get there on its own. Its auto-vectorizer rewrites simple loops into vector instructions. But JEP 508 is blunt about the limits: the set of transformable operations is limited, it is fragile with respect to changes in code shape, and some code (for example `Arrays.hashCode`) is never transformed at all. You cannot see whether it worked, and you cannot ask for it.

## The trick

The incubating `jdk.incubator.vector` module lets you write the vector loop yourself, in plain Java, and have the JIT compile it to the real instructions. Four pieces are enough for most kernels:

* A **species** says which element type and how many bits per vector: `FloatVector.SPECIES_PREFERRED` is the best shape for the CPU you are running on.
* `FloatVector.fromArray(species, array, offset)` loads one vector, `intoArray` stores one, and `mul`, `add`, `fma` and friends work on all lanes at once.
* `species.loopBound(n)` is the largest multiple of the lane count that is at most `n`. The main loop runs up to it, and a **mask** from `species.indexInRange(i, n)` covers the leftover tail.
* `reduceLanes(VectorOperators.ADD)` folds the lanes of a vector into one scalar.

```java
var species = FloatVector.SPECIES_PREFERRED;
for (int i = 0; i < species.loopBound(n); i += species.length()) {
    var va = FloatVector.fromArray(species, a, i);
    var vb = FloatVector.fromArray(species, b, i);
    va.mul(vb).intoArray(y, i);
}
```

Because it is an incubator module, you opt in with `--add-modules jdk.incubator.vector` for both `javac` and `java`. The JVM then prints `WARNING: Using incubator modules: jdk.incubator.vector` on stderr at startup.

## Full example

The first program checks correctness only, and everything it prints is deterministic: an elementwise `a * b + c` with a masked tail, a fused multiply-add, an integer sum, a float sum and a threshold count. The array length is 1003, which is not a multiple of any lane count, so the tail always matters. The results do not depend on how wide the vectors are on your CPU.

```java run args="--add-modules jdk.incubator.vector"
import java.util.Arrays;
import java.util.Random;
import jdk.incubator.vector.FloatVector;
import jdk.incubator.vector.IntVector;
import jdk.incubator.vector.VectorMask;
import jdk.incubator.vector.VectorOperators;
import jdk.incubator.vector.VectorSpecies;

public class VectorDemo {

    static final VectorSpecies<Float> F = FloatVector.SPECIES_PREFERRED;
    static final VectorSpecies<Integer> I = IntVector.SPECIES_PREFERRED;

    // y[i] = a[i] * b[i] + c[i], one element at a time.
    static void scalarMulAdd(float[] a, float[] b, float[] c, float[] y) {
        for (int i = 0; i < a.length; i++) {
            y[i] = a[i] * b[i] + c[i];
        }
    }

    // The same thing, one vector at a time. The tail (fewer elements than lanes) uses a mask.
    static void vectorMulAdd(float[] a, float[] b, float[] c, float[] y) {
        int i = 0;
        for (int bound = F.loopBound(a.length); i < bound; i += F.length()) {
            var va = FloatVector.fromArray(F, a, i);
            var vb = FloatVector.fromArray(F, b, i);
            var vc = FloatVector.fromArray(F, c, i);
            va.mul(vb).add(vc).intoArray(y, i);
        }
        if (i < a.length) {
            VectorMask<Float> tail = F.indexInRange(i, a.length);
            var va = FloatVector.fromArray(F, a, i, tail);
            var vb = FloatVector.fromArray(F, b, i, tail);
            var vc = FloatVector.fromArray(F, c, i, tail);
            va.mul(vb).add(vc).intoArray(y, i, tail);
        }
    }

    static int scalarSum(int[] data) {
        int sum = 0;
        for (int value : data) sum += value;
        return sum;
    }

    static int vectorSum(int[] data) {
        var acc = IntVector.zero(I);
        int i = 0;
        for (int bound = I.loopBound(data.length); i < bound; i += I.length()) {
            acc = acc.add(IntVector.fromArray(I, data, i));
        }
        int sum = acc.reduceLanes(VectorOperators.ADD);   // one horizontal step at the very end
        for (; i < data.length; i++) sum += data[i];      // scalar tail
        return sum;
    }

    // How many elements are above a threshold? A mask is a vector of booleans, and trueCount() counts them.
    static int vectorCountAbove(float[] data, float threshold) {
        int count = 0;
        int i = 0;
        for (int bound = F.loopBound(data.length); i < bound; i += F.length()) {
            count += FloatVector.fromArray(F, data, i).compare(VectorOperators.GT, threshold).trueCount();
        }
        for (; i < data.length; i++) if (data[i] > threshold) count++;
        return count;
    }

    public static void main(String[] args) {
        var random = new Random(42);
        int n = 1003;   // deliberately not a multiple of any lane count
        float[] a = new float[n], b = new float[n], c = new float[n];
        for (int i = 0; i < n; i++) {
            a[i] = random.nextFloat();
            b[i] = random.nextFloat();
            c[i] = random.nextFloat();
        }

        float[] scalar = new float[n], vector = new float[n];
        scalarMulAdd(a, b, c, scalar);
        vectorMulAdd(a, b, c, vector);
        System.out.println("mul+add identical to scalar loop: " + Arrays.equals(scalar, vector));

        // Fused multiply-add rounds once instead of twice, so it matches Math.fma, not a * b + c.
        float[] fused = new float[n];
        for (int i = 0; i + F.length() <= n; i += F.length()) {
            FloatVector.fromArray(F, a, i).fma(FloatVector.fromArray(F, b, i), FloatVector.fromArray(F, c, i)).intoArray(fused, i);
        }
        int checked = F.loopBound(n);
        boolean matchesMathFma = true;
        for (int i = 0; i < checked; i++) matchesMathFma &= fused[i] == Math.fma(a[i], b[i], c[i]);
        System.out.println("fma identical to Math.fma:        " + matchesMathFma);

        int[] ints = random.ints(n, -1000, 1000).toArray();
        System.out.println("int sum equal: " + (scalarSum(ints) == vectorSum(ints)) + " (" + scalarSum(ints) + ")");

        float expected = 0;
        for (float value : a) expected += value;
        var acc = FloatVector.zero(F);
        int i = 0;
        for (int bound = F.loopBound(n); i < bound; i += F.length()) acc = acc.add(FloatVector.fromArray(F, a, i));
        float vectorTotal = acc.reduceLanes(VectorOperators.ADD);
        for (; i < n; i++) vectorTotal += a[i];
        System.out.println("float sum within 1e-5 (relative) of scalar: " + (Math.abs(expected - vectorTotal) < 1e-5f * expected));

        int expectedCount = 0;
        for (float value : a) if (value > 0.75f) expectedCount++;
        System.out.println("above 0.75: " + vectorCountAbove(a, 0.75f) + " (scalar says " + expectedCount + ")");
    }
}
```

Output:

```text output
mul+add identical to scalar loop: true
fma identical to Math.fma:        true
int sum equal: true (-19806)
float sum within 1e-5 (relative) of scalar: true
above 0.75: 240 (scalar says 240)
```

The second program is a timing sketch. Its output is **nondeterministic**: the block is flagged that way, only has to exit cleanly, and the output below is one real run on an Apple M3 (128-bit NEON, four float lanes). Yours will differ in the numbers, and the lane count differs per CPU.

```java run args="--add-modules jdk.incubator.vector" nondeterministic
import java.util.Random;
import java.util.function.Supplier;
import jdk.incubator.vector.FloatVector;
import jdk.incubator.vector.VectorOperators;
import jdk.incubator.vector.VectorSpecies;

public class VectorTiming {

    static final VectorSpecies<Float> F = FloatVector.SPECIES_PREFERRED;

    static void scalarMulAdd(float[] a, float[] b, float[] c, float[] y) {
        for (int i = 0; i < a.length; i++) y[i] = a[i] * b[i] + c[i];
    }

    static void vectorMulAdd(float[] a, float[] b, float[] c, float[] y) {
        int bound = F.loopBound(a.length);
        for (int i = 0; i < bound; i += F.length()) {
            FloatVector.fromArray(F, a, i).mul(FloatVector.fromArray(F, b, i))
                    .add(FloatVector.fromArray(F, c, i)).intoArray(y, i);
        }
    }

    static float scalarSum(float[] data) {
        float sum = 0;
        for (float value : data) sum += value;   // strict left-to-right order, so no auto-vectorization
        return sum;
    }

    static float vectorSum(float[] data) {
        var acc = FloatVector.zero(F);
        int bound = F.loopBound(data.length);
        for (int i = 0; i < bound; i += F.length()) {
            acc = acc.add(FloatVector.fromArray(F, data, i));
        }
        return acc.reduceLanes(VectorOperators.ADD);
    }

    static double millis(Runnable work) {
        long start = System.nanoTime();
        work.run();
        return (System.nanoTime() - start) / 1e6;
    }

    public static void main(String[] args) {
        var random = new Random(1);
        int n = 1 << 14;   // 16384 floats: small enough to stay in cache, so we measure compute
        float[] a = new float[n], b = new float[n], c = new float[n], y = new float[n];
        for (int i = 0; i < n; i++) { a[i] = random.nextFloat(); b[i] = random.nextFloat(); c[i] = random.nextFloat(); }
        int reps = 20_000;
        float[] sink = new float[1];

        System.out.println("preferred species: " + F);
        for (int round = 1; round <= 3; round++) {   // later rounds run on JIT-compiled code
            double mulAddScalar = millis(() -> { for (int r = 0; r < reps; r++) scalarMulAdd(a, b, c, y); });
            double mulAddVector = millis(() -> { for (int r = 0; r < reps; r++) vectorMulAdd(a, b, c, y); });
            double sumScalar = millis(() -> { for (int r = 0; r < reps; r++) sink[0] += scalarSum(a); });
            double sumVector = millis(() -> { for (int r = 0; r < reps; r++) sink[0] += vectorSum(a); });
            System.out.printf("round %d: a*b+c scalar %6.1f ms, vector %6.1f ms | sum scalar %6.1f ms, vector %6.1f ms%n",
                    round, mulAddScalar, mulAddVector, sumScalar, sumVector);
        }
        if (sink[0] == 42) System.out.println();
        System.out.printf("scalar sum %.4f, vector sum %.4f%n", scalarSum(a), vectorSum(a));
    }
}
```

Output:

```text output
preferred species: Species[float, 4, S_128_BIT]
round 1: a*b+c scalar   56.4 ms, vector   88.6 ms | sum scalar  247.2 ms, vector   69.4 ms
round 2: a*b+c scalar   43.1 ms, vector   55.5 ms | sum scalar  251.1 ms, vector   60.1 ms
round 3: a*b+c scalar   50.8 ms, vector   52.9 ms | sum scalar  243.0 ms, vector   61.1 ms
scalar sum 8217.2373, vector sum 8217.2334
```

A hand-rolled `System.nanoTime()` loop is not a benchmark. There is no fork, no isolation from the JIT's whole-program decisions, and the numbers move from run to run, as you can see between rounds. It is enough to show the shape. For anything you intend to quote or decide on, use [JMH](https://github.com/openjdk/jmh).

## How it works

* **A species is a shape.** `SPECIES_PREFERRED` prints as `Species[float, 4, S_128_BIT]` here: four 32-bit lanes in a 128-bit register. The same code on an AVX2 machine gets eight lanes, on AVX-512 sixteen. The program never mentions the lane count, so the same source adapts.
* **`loopBound` plus a mask handles the tail.** `loopBound(1003)` rounds down to a multiple of the lane count, so the main loop never reads past the end. For the last few elements, `indexInRange(i, n)` builds a mask whose first `n - i` lanes are set. A masked load fills the other lanes with zero, and a masked store leaves the array untouched there. The alternative is a plain scalar loop for the tail, which `vectorSum` and `vectorCountAbove` use.
* **`mul` then `add` is bit-identical to the scalar loop.** Each lane does the same IEEE multiply and the same IEEE add that the scalar code would, in the same order, so `Arrays.equals` says `true`. `fma` rounds once instead of twice, which is why it is compared against `Math.fma` and not against `a * b + c`.
* **Reductions are different.** Integer addition is associative, so the vector sum equals the scalar sum exactly. Float addition is not. The vector code adds lane-wise partial sums and combines them at the end, which is a different order, and the `reduceLanes` Javadoc says the result "will reflect the choice of an arbitrary order of operations, which may even vary over time". The result is close but not necessarily identical, and it can depend on the lane count. That is why the example only asserts a relative tolerance. Accumulate in a vector register and call `reduceLanes` once after the loop, because the horizontal step is the slow one.
* **Masks are booleans in registers.** `compare(GT, threshold)` returns a `VectorMask` and `trueCount()` counts its set lanes. That is a branch-free "how many elements are above this value", and masks are also the tool for conditional updates (`blend`, masked stores).
* **The JIT has to cooperate.** C2 recognizes the vector operations as intrinsics and maps each vector value to a register, eliding the allocation of the `FloatVector` objects. Until the code is compiled, in the interpreter, they are real objects. That is part of why round 1 in the timing run is slower than round 3.
* **What the timing sample shows.** The `a * b + c` loop is no faster with the Vector API than without it (slightly slower in this run): the plain scalar version is simple enough that HotSpot auto-vectorizes it. The float sum is about 4 times faster, because the scalar loop must add in strict left-to-right order and so cannot be auto-vectorized, while the Vector API has been told explicitly that a different order is acceptable. The Vector API earns its keep where the auto-vectorizer gives up.

### Why still incubating

The goal of the module is to make `FloatVector` and its siblings value classes: objects without identity that the JIT can keep in registers and flatten into arrays and fields, with no special-casing. That is Project Valhalla (JEP 401). Today they are value-based classes with special handling in C2. JEP 508 states that the API "will incubate until necessary features of Project Valhalla become available as preview features", and then it will move to preview. Meanwhile each release re-incubates it: JEP 338 in Java 16, then one JEP per release up to JEP 508 in Java 25, JEP 529 in 26 and JEP 537, the twelfth incubator, in Java 27. The API changes a little each time. The example was verified on 25 and also runs on 17, 24 and 27, and it compiles with `--release 16`, but do not assume code written against one release compiles against the next without a look.

## Gotchas

* **It is an incubator module.** You need `--add-modules jdk.incubator.vector` on `javac` and `java`, and every launch prints the warning on stderr. Build tools need the flag in their compiler and test configuration. Treat it as a dependency you will have to revisit on each JDK upgrade.
* **Without hardware support it is slow, not wrong.** The package documentation says every operation has a default scalar implementation that is used when it cannot be compiled to vector instructions. Hard-coding `SPECIES_512` on a CPU with 256-bit vectors takes that route, and a scalar fallback wrapped in vector objects is not what you wanted. Use `SPECIES_PREFERRED`, and measure on the hardware you deploy on.
* **Float results depend on the lane count.** Two machines with different vector widths can produce different float sums from the same code. Do not compare them with `==`, and do not use the Vector API where bit-reproducible floating point is a requirement.
* **`fromArray` is bounds checked.** `fromArray(species, a, i)` throws `IndexOutOfBoundsException` when `i + lanes` exceeds the array length. Stay under `loopBound` or use a mask.
* **Vectors are value-based.** Do not synchronize on them or compare them with `==`. The Javadoc is explicit that locals, parameters and `static final` constants are fine, while storing vectors in other fields or array elements may incur performance risks.
* **Beware the cold start.** The interpreter allocates a real object for every intermediate vector. A short-lived program, or a method that runs only a few times, may be slower with vectors than without.
* **Auto-vectorization is free.** Before rewriting a loop, check that the plain version is not already fast enough. The sample's `a * b + c` kernel is the proof.

## When to use it (and when not to)

Use it for numeric kernels that dominate a profile and that the auto-vectorizer does not handle: reductions over floating point, data-dependent selection with masks, shuffles, checksums and hashes, parsing and scanning loops, image and signal processing, small linear algebra. Always keep the scalar version as a reference and as a test oracle, exactly as the example does.

Do not use it for ordinary application code, for loops that already auto-vectorize, or in a library that promises long-term source compatibility without isolating the vector code behind an interface and a scalar fallback. And do not reach for it before you have a profile that says the loop is hot.

## Related

* [094 · Bit Twiddling Hacks](094-bit-twiddling.md), SIMD within a single register, with no incubator flag
* [089 · Calling C Without JNI: The Foreign Function and Memory API](089-foreign-function-memory.md), whose `MemorySegment` the Vector API can load from and store to
* [091 · Custom JFR Events: A Flight Recorder for Your Own Code](091-custom-jfr-events.md), for measuring what the hot loop costs in a real application

## Sources

* [JEP 508: Vector API (Tenth Incubator)](https://openjdk.org/jeps/508), with the motivation, the history and the Valhalla plan
* [JEP 338: Vector API (Incubator)](https://openjdk.org/jeps/338) and [JEP 537: Vector API (Twelfth Incubator)](https://openjdk.org/jeps/537)
* [`jdk.incubator.vector` package Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/jdk.incubator.vector/jdk/incubator/vector/package-summary.html)
* [JMH](https://github.com/openjdk/jmh), the Java Microbenchmark Harness
