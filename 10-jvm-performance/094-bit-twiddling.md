# 094 · Bit Twiddling Hacks

> Check for a power of two with one subtraction, isolate a bit with a negation, enumerate subsets with a counter. Most of these tricks are older than Java, and a few now have names in `java.lang.Integer`.

**Since:** Java 19 · **Category:** [JVM, Reflection and Performance](../README.md#jvm-reflection-and-performance) · **Level:** Intermediate · **Verdict:** ⚠️ Situational

## The problem

Business code rarely touches individual bits. Hash tables, flag sets, binary protocols, bitboards, packed IDs, spatial indexes and compilers do, and in that code the obvious solution is often a loop: count the set bits one at a time, find the next power of two by doubling, test every subset with a nested `if`.

There is a body of knowledge for this, collected in Henry S. Warren's book *Hacker's Delight* and on Sean Eron Anderson's "Bit Twiddling Hacks" page. The tricks all exploit one fact about two's complement arithmetic: adding or subtracting one has a very regular effect on the low bits, so a subtraction plus an AND does the work of a loop.

## The trick

The two most useful identities for a non-zero `x`:

```java
x & (x - 1)    // clears the lowest set bit
x & -x         // keeps only the lowest set bit (same as Integer.lowestOneBit(x))
```

The first one gives you the power-of-two test (`x > 0 && (x & (x - 1)) == 0`) and a loop over the set bits (`for (; x != 0; x &= x - 1)`). The second isolates a bit, which is the basis of Fenwick trees and of Gosper's hack below. Everything else in this document is a variation.

The trick works on any Java version. The example uses `Integer.compress` and `Integer.expand`, which arrived in Java 19, hence the badge.

## Full example

One program, nine small sections, all deterministic. Each section prints enough to see the effect, including the traps.

```java run
import java.util.ArrayList;
import java.util.List;

public class BitTricks {

    static String bin(int x, int width) {
        return String.format("%" + width + "s", Integer.toBinaryString(x)).replace(' ', '0');
    }

    // 1. A power of two has exactly one bit set, and x & (x - 1) clears the lowest set bit.
    static boolean isPowerOfTwo(int x) { return x > 0 && (x & (x - 1)) == 0; }

    // 2. x & -x isolates the lowest set bit. Repeating "x &= x - 1" visits the set bits one by one.
    static List<Integer> positionsOfSetBits(int x) {
        var positions = new ArrayList<Integer>();
        for (; x != 0; x &= x - 1) positions.add(Integer.numberOfTrailingZeros(x));
        return positions;
    }

    // 3. The smallest power of two >= x, valid for 1..2^30. This is what HashMap does for its table size.
    static int nextPowerOfTwo(int x) { return 1 << (32 - Integer.numberOfLeadingZeros(x - 1)); }

    // 4. Branch-free absolute value: the sign mask is 0 for x >= 0 and -1 (all ones) for x < 0.
    static int abs(int x) { int mask = x >> 31; return (x ^ mask) - mask; }
    static int signum(int x) { return (x >> 31) | (-x >>> 31); }

    // 5. XOR swap. Clever, and subtly broken.
    static void xorSwap(int[] a, int i, int j) {
        a[i] ^= a[j];
        a[j] ^= a[i];
        a[i] ^= a[j];
    }

    // 6. Two ints in one long, for example a grid coordinate used as a map key without allocating a Point.
    static long pack(int hi, int lo) { return ((long) hi << 32) | (lo & 0xFFFFFFFFL); }
    static int hi(long packed) { return (int) (packed >>> 32); }
    static int lo(long packed) { return (int) packed; }

    public static void main(String[] args) {
        System.out.println("-- power of two");
        for (int x : new int[] {0, 1, 6, 64, 1 << 30, Integer.MIN_VALUE}) {
            System.out.printf("%11d bitCount=%d -> %b%n", x, Integer.bitCount(x), isPowerOfTwo(x));
        }
        System.out.println("MIN_VALUE & (MIN_VALUE - 1) == 0 too, hence the x > 0 test: "
                + ((Integer.MIN_VALUE & (Integer.MIN_VALUE - 1)) == 0));

        System.out.println("-- lowest set bit");
        int x = 0b0101_1000;
        System.out.println(bin(x, 8) + " & -x = " + bin(x & -x, 8) + ", lowestOneBit = " + bin(Integer.lowestOneBit(x), 8));
        System.out.println(bin(x, 8) + " has bits at " + positionsOfSetBits(x));

        System.out.println("-- the Integer toolbox for 0x12345678");
        int v = 0x12345678;
        System.out.printf("bitCount=%d highestOneBit=%08x leadingZeros=%d trailingZeros=%d%n",
                Integer.bitCount(v), Integer.highestOneBit(v),
                Integer.numberOfLeadingZeros(v), Integer.numberOfTrailingZeros(v));
        System.out.printf("reverse=%08x reverseBytes=%08x rotateLeft(8)=%08x rotateRight(8)=%08x%n",
                Integer.reverse(v), Integer.reverseBytes(v), Integer.rotateLeft(v, 8), Integer.rotateRight(v, 8));

        System.out.println("-- next power of two, and masking instead of modulo");
        for (int n : new int[] {1, 2, 3, 17, 1000, 1024, 1025}) {
            System.out.printf("nextPowerOfTwo(%d) = %d%n", n, nextPowerOfTwo(n));
        }
        System.out.printf("-5 & 7 = %d, -5 %% 8 = %d, Math.floorMod(-5, 8) = %d%n", -5 & 7, -5 % 8, Math.floorMod(-5, 8));

        System.out.println("-- sign tricks");
        System.out.printf("abs(-7) = %d, abs(7) = %d, signum(-9, 0, 9) = %d %d %d%n",
                abs(-7), abs(7), signum(-9), signum(0), signum(9));
        System.out.println("abs(MIN_VALUE) = " + abs(Integer.MIN_VALUE) + " (Math.abs agrees: "
                + (Math.abs(Integer.MIN_VALUE) == Integer.MIN_VALUE) + ")");

        System.out.println("-- XOR swap");
        int[] pair = {3, 9};
        xorSwap(pair, 0, 1);
        System.out.println("swap(3, 9)         -> " + List.of(pair[0], pair[1]));
        int[] same = {3, 9};
        xorSwap(same, 1, 1);
        System.out.println("swap with itself   -> " + List.of(same[0], same[1]) + " (the 9 turned into 0)");

        System.out.println("-- two ints in a long");
        long packed = pack(7, -2);
        System.out.println("pack(7, -2) = 0x" + Long.toHexString(packed) + " -> " + hi(packed) + ", " + lo(packed));
        long careless = ((long) 7 << 32) | -2;   // forgot the 0xFFFFFFFFL mask: -2 sign-extends over the high half
        System.out.println("without the mask  -> " + hi(careless) + ", " + lo(careless));

        System.out.println("-- all subsets of a set, as bit masks over {A, B, C, D}");
        String names = "ABCD";
        int universe = 0b1011;   // {A, B, D}
        var subsets = new ArrayList<String>();
        for (int sub = universe; ; sub = (sub - 1) & universe) {   // submasks, largest first
            subsets.add(describe(sub, names));
            if (sub == 0) break;
        }
        System.out.println("subsets of " + describe(universe, names) + ": " + subsets);

        var pairs = new ArrayList<String>();
        for (int s = 0b11; s < (1 << 4); ) {   // Gosper's hack: next integer with the same bit count
            pairs.add(describe(s, names));
            int lowest = s & -s;
            int ripple = s + lowest;
            s = (((ripple ^ s) >>> 2) / lowest) | ripple;
        }
        System.out.println("2-element subsets of {A, B, C, D}: " + pairs);

        System.out.println("-- Integer.compress and Integer.expand (Java 19)");
        int packedFields = 0b1011_0110;
        int mask = 0b0111_0010;
        int gathered = Integer.compress(packedFields, mask);
        System.out.println("compress(" + bin(packedFields, 8) + ", " + bin(mask, 8) + ") = " + bin(gathered, 4));
        System.out.println("expand(" + bin(gathered, 4) + ", " + bin(mask, 8) + ")      = " + bin(Integer.expand(gathered, mask), 8));

        // Morton code: interleave the bits of x and y by spreading each over alternate positions.
        int px = 0b1011, py = 0b0110;
        int morton = Integer.expand(px, 0x55555555) | Integer.expand(py, 0xAAAAAAAA);
        System.out.println("morton(" + bin(px, 4) + ", " + bin(py, 4) + ") = " + bin(morton, 8)
                + ", back to (" + bin(Integer.compress(morton, 0x55555555), 4)
                + ", " + bin(Integer.compress(morton, 0xAAAAAAAA), 4) + ")");
    }

    static String describe(int mask, String names) {
        var sb = new StringBuilder("{");
        for (int i = 0; i < names.length(); i++) {
            if ((mask & (1 << i)) != 0) sb.append(sb.length() > 1 ? "," : "").append(names.charAt(i));
        }
        return sb.append('}').toString();
    }
}
```

Output:

```text output
-- power of two
          0 bitCount=0 -> false
          1 bitCount=1 -> true
          6 bitCount=2 -> false
         64 bitCount=1 -> true
 1073741824 bitCount=1 -> true
-2147483648 bitCount=1 -> false
MIN_VALUE & (MIN_VALUE - 1) == 0 too, hence the x > 0 test: true
-- lowest set bit
01011000 & -x = 00001000, lowestOneBit = 00001000
01011000 has bits at [3, 4, 6]
-- the Integer toolbox for 0x12345678
bitCount=13 highestOneBit=10000000 leadingZeros=3 trailingZeros=3
reverse=1e6a2c48 reverseBytes=78563412 rotateLeft(8)=34567812 rotateRight(8)=78123456
-- next power of two, and masking instead of modulo
nextPowerOfTwo(1) = 1
nextPowerOfTwo(2) = 2
nextPowerOfTwo(3) = 4
nextPowerOfTwo(17) = 32
nextPowerOfTwo(1000) = 1024
nextPowerOfTwo(1024) = 1024
nextPowerOfTwo(1025) = 2048
-5 & 7 = 3, -5 % 8 = -5, Math.floorMod(-5, 8) = 3
-- sign tricks
abs(-7) = 7, abs(7) = 7, signum(-9, 0, 9) = -1 0 1
abs(MIN_VALUE) = -2147483648 (Math.abs agrees: true)
-- XOR swap
swap(3, 9)         -> [9, 3]
swap with itself   -> [3, 0] (the 9 turned into 0)
-- two ints in a long
pack(7, -2) = 0x7fffffffe -> 7, -2
without the mask  -> -1, -2
-- all subsets of a set, as bit masks over {A, B, C, D}
subsets of {A,B,D}: [{A,B,D}, {B,D}, {A,D}, {D}, {A,B}, {B}, {A}, {}]
2-element subsets of {A, B, C, D}: [{A,B}, {A,C}, {B,C}, {A,D}, {B,D}, {C,D}]
-- Integer.compress and Integer.expand (Java 19)
compress(10110110, 01110010) = 0111
expand(0111, 01110010)      = 00110010
morton(1011, 0110) = 01101101, back to (1011, 0110)
```

## How it works

* **`x & (x - 1)`.** Subtracting 1 turns the lowest set bit into 0 and every zero below it into 1. ANDing with the original clears exactly that one bit. If nothing else is left, `x` had a single bit, so it was a power of two. That is also why the loop `x &= x - 1` runs once per set bit and not once per bit position.
* **`x & -x`.** Since `-x` is `~x + 1`, negation flips every bit above the lowest set bit and keeps that bit and the zeros below it. The AND of both leaves just the lowest set bit.
* **The `Integer` toolbox.** Most of the hacks you find on the old pages are `bitCount`, `highestOneBit`, `lowestOneBit`, `numberOfLeadingZeros`, `numberOfTrailingZeros`, `reverse`, `reverseBytes`, `rotateLeft` and `rotateRight`. The JDK source of `Integer` credits *Hacker's Delight* for this material, and many of these methods are `@IntrinsicCandidate`, so the JIT may replace them with a single instruction (`POPCNT`, `LZCNT` and friends) on CPUs that have one. Prefer the named method to a hand-rolled version every time. `Long` has the same set.
* **Next power of two.** For 17, `x - 1` is `10000`, which has 27 leading zeros, so `1 << (32 - 27)` is 32. Subtracting 1 first makes exact powers of two map to themselves (1024 stays 1024). `HashMap.tableSizeFor` computes the same thing with `-1 >>> Integer.numberOfLeadingZeros(cap - 1)`, plus a clamp at both ends. The one-liner is only valid for 1 to 2^30. Above that, the shift overflows.
* **Masking instead of modulo.** `x & 7` is `x mod 8` for non-negative `x`. For negative `x` it is not the remainder operator, because `%` keeps the sign (-5 % 8 is -5), but it is exactly `Math.floorMod`, which is what a hash table index wants.
* **Sign tricks.** `x >> 31` is 0 for non-negative and -1 (all ones) for negative numbers, an arithmetic shift copies the sign bit. XOR with an all-ones mask flips every bit, and subtracting -1 adds 1, which together is two's complement negation. `abs` and `signum` follow, without a branch. The trap is `Integer.MIN_VALUE`: its negation is itself, so `abs(MIN_VALUE)` is still negative. `Math.abs` has the same problem, and `Math.absExact` throws instead.
* **XOR swap.** `a ^= b; b ^= a; a ^= b;` swaps without a temporary. It also breaks when both operands are the same variable or array slot, as the output shows: the first XOR zeroes the value and there is nothing left to restore. It also gains nothing: the swap with a temporary is one plain `int` held in a register, and the XOR version is a chain of three dependent operations. It is a nice puzzle and a bad idea.
* **Two ints in a long.** `pack` shifts the high half up and masks the low half with `0xFFFFFFFFL`. Without the mask, a negative `lo` is sign-extended to 64 bits, and its ones overwrite the high half: `(7, -2)` came back as `(-1, -2)`. `Integer.toUnsignedLong(lo)` is the readable spelling of the mask. This is the cheap way to use a pair of ints as a `Map<Long, V>` key or to sort pairs without allocating.
* **Subsets as counters.** A set of up to 64 elements is a `long` of flags, and `java.util.EnumSet` is exactly that under the hood (`RegularEnumSet` keeps a single `long`). Enumerating all submasks of `universe` is `sub = (sub - 1) & universe`: subtracting 1 clears the lowest set bit and sets everything below, and the AND throws away the bits that are not in the universe. It visits each of the 2^k submasks of a k-element set exactly once, in decreasing order.
* **Gosper's hack.** The loop with `lowest` and `ripple` computes the next larger integer with the same number of set bits (Hacker's Delight calls this `snoob`, and it is item 175 of the MIT HAKMEM memo of 1972, credited to Bill Gosper). Start at `0b11` and you walk through all 2-element subsets of a 4-element set in increasing order, without ever visiting the other ten masks.
* **`compress` and `expand` (Java 19).** `compress(i, mask)` gathers the bits of `i` selected by `mask` into the low bits of the result. `expand` is the inverse: it scatters the low bits to the positions selected by the mask. They are `PEXT` and `PDEP` in x86 BMI2 terms and `@IntrinsicCandidate` in the JDK. The Morton code at the end is the classic use: `expand(x, 0x55555555) | expand(y, 0xAAAAAAAA)` interleaves two numbers bit by bit, which keeps points that are close in 2D close in a 1D key. `compress` takes them apart again.

## Gotchas

* **Shift distances are masked.** For an `int`, `1 << 32` is `1`, not `0`, and `x << -1` is `x << 31`, because only the low five bits of the distance count (six for `long`). Code that computes a shift distance needs to handle 32 on its own.
* **`>>` versus `>>>`.** `>>` copies the sign bit, `>>>` shifts in zeros. Using the wrong one on a negative value is the most common bug in this family. See [059](../07-puzzlers/059-integer-overflow.md).
* **Sign extension on widening.** Anything that turns a negative `int` or `byte` into a `long` without a mask drags a trail of ones with it: `(long) -2` is `0xFFFFFFFFFFFFFFFE`.
* **Do not hand-roll what the JDK names.** `Integer.bitCount(x)` beats the loop and beats the clever bit-parallel version you copied from the internet. `EnumSet`, `BitSet` and `Integer.compress` beat DIY flag arithmetic.
* **Do not optimize division by constants.** `x / 8` and `x % 8` on a constant are already strength-reduced by the JIT. Writing `x >> 3` by hand saves nothing and gets negative numbers wrong.
* **Check against the dull version.** Every trick here has an obvious loop-based equivalent. Test the clever one against the naive one on random inputs ([026](../03-build-it-yourself/026-property-based-testing.md)), including `0`, `-1`, `MIN_VALUE` and `MAX_VALUE`.
* **Comment the invariant, not the operation.** `// x & (x - 1) clears the lowest set bit` explains nothing a reader cannot see. `// capacity must be a power of two so we can mask` explains why the code is there.

## When to use it (and when not to)

Use the named `Integer` and `Long` methods freely, they are readable and fast. Use the identities in code where bits are the domain: hash tables and caches that size themselves to powers of two, bitboards, Bloom filters, compact keys, protocol parsing, graph and DP algorithms over subsets of a small set (the submask loop is the engine of the classic travelling salesman bitmask DP).

Do not use them to be clever in ordinary application code. A reader who needs Hacker's Delight open to understand your `if` is a cost, and the JIT is better at micro-optimizations than most people expect. The XOR swap is a party trick. For many elements at once, see the [Vector API](093-vector-api.md) instead of hand-rolling SIMD within a register.

## Related

* [059 · Integer Overflow and Arithmetic Surprises](../07-puzzlers/059-integer-overflow.md), where `MIN_VALUE` and masking bite
* [026 · Property-Based Testing in 80 Lines](../03-build-it-yourself/026-property-based-testing.md), to test a clever trick against the obvious one
* [093 · SIMD in Java with the Vector API (Incubator)](093-vector-api.md), the same idea at 128 to 512 bits wide
* [056 · "Aa" Equals "BB" (in hashCode)](../06-hidden-corners/056-hashcode-collisions.md), for the other side of power-of-two hash tables

## Sources

* Henry S. Warren, Jr., *Hacker's Delight*, 2nd edition, Addison-Wesley, 2012
* Sean Eron Anderson, [Bit Twiddling Hacks](https://graphics.stanford.edu/~seander/bithacks.html)
* [`java.lang.Integer` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/Integer.html), including `compress` and `expand`
* [HAKMEM, programming hacks](https://www.inwap.com/pdp10/hbaker/hakmem/hacks.html), the 1972 MIT AI memo, where item 175 is Gosper's next-same-popcount trick
