# 056 · "Aa" Equals "BB" (in hashCode)

> Two different strings with the same hash code, plus a one-line recipe for as many more as you like. It is the reason `HashMap` grew trees in Java 8, and why `switch` on a string is more than a hash lookup.

**Since:** Java 16 · **Category:** [Hidden Corners and Party Tricks](../README.md#hidden-corners-and-party-tricks) · **Level:** Intermediate · **Verdict:** 🧪 Party trick

## The problem

`String.hashCode()` returns an `int`. There are far more strings than ints, so collisions must exist, and every hash table is built to survive them. Normally you never see one. But the hash function is not secret, not salted and not randomized: the Javadoc specifies it exactly, so it can never change. Anyone can compute strings that land in the same bucket, and a hash table that gets thousands of keys in one bucket stops being a hash table.

## The trick

The specified formula is `s[0]*31^(n-1) + s[1]*31^(n-2) + ... + s[n-1]`, in `int` arithmetic. Work it out for two characters:

* `"Aa"`: `'A' * 31 + 'a'` = `65 * 31 + 97` = 2112
* `"BB"`: `'B' * 31 + 'B'` = `66 * 31 + 66` = 2112

Moving one step up the alphabet in the first character adds 31, and dropping the second character by 31 cancels it exactly: `'a'` is 31 above `'B'`. So `"Aa"` and `"BB"` are a collision.

The hash is a polynomial, so equal-length collisions can be **concatenated**. If `x` and `y` have the same length and the same hash, then `p + x` and `p + y` collide for any prefix `p`, and so do `x + s` and `y + s` for any suffix `s`. Build strings out of blocks that are each either `"Aa"` or `"BB"`, and `n` blocks give you `2^n` different strings with one shared hash code. Ten blocks, twenty characters, 1024 colliding keys.

## Full example

The program below checks the formula, builds the colliding families, and then watches what `HashMap` does about them. The `Hashtable` is there as a stand-in for the pre-Java 8 `HashMap`, which also chained colliding entries in a plain linked list. Peeking at `HashMap` and `String` internals needs `--add-opens`, because they are implementation details, not API.

```java run args="--add-opens java.base/java.util=ALL-UNNAMED --add-opens java.base/java.lang=ALL-UNNAMED"
import java.lang.reflect.Field;
import java.util.*;
import java.util.function.Function;

public class HashCollisions {

    // The documented formula, written out by hand.
    static int hashByHand(String s) {
        int h = 0;
        for (char c : s.toCharArray()) h = 31 * h + c;
        return h;
    }

    // Every string made of n blocks that are each "Aa" or "BB": 2^n strings, one hash code.
    static List<String> colliding(int blocks) {
        List<String> result = List.of("");
        for (int i = 0; i < blocks; i++) {
            List<String> next = new ArrayList<>();
            for (String prefix : result) {
                next.add(prefix + "Aa");
                next.add(prefix + "BB");
            }
            result = next;
        }
        return result;
    }

    static String label(String s) {
        return switch (s) {
            case "Aa" -> "first";
            case "BB" -> "second";
            default -> "other";
        };
    }

    // A key that borrows String's hash and counts how often equals and compareTo run.
    static class PlainKey {
        static long equalsCalls, compareCalls;
        final String text;
        PlainKey(String text) { this.text = text; }
        @Override public int hashCode() { return text.hashCode(); }
        @Override public boolean equals(Object o) {
            equalsCalls++;
            return o instanceof PlainKey other && other.text.equals(text);
        }
    }

    // The same key, but sortable. Like String, it implements Comparable<itself>.
    static final class SortableKey extends PlainKey implements Comparable<SortableKey> {
        SortableKey(String text) { super(text); }
        @Override public int compareTo(SortableKey other) {
            compareCalls++;
            return text.compareTo(other.text);
        }
    }

    // Puts every key in, then looks every key up once and reports the work done by the lookups.
    static <K> String lookupCost(Map<K, Integer> map, Function<String, K> key, List<String> texts) {
        for (String text : texts) map.put(key.apply(text), 1);
        PlainKey.equalsCalls = 0;
        PlainKey.compareCalls = 0;
        for (String text : texts) map.get(key.apply(text));
        return "equals=" + PlainKey.equalsCalls + " compareTo=" + PlainKey.compareCalls;
    }

    // Reads the first occupied slot of a HashMap: table length and the class of its first node.
    static String firstBin(HashMap<?, ?> map) throws Exception {
        Field table = HashMap.class.getDeclaredField("table");
        table.setAccessible(true);
        for (Object node : (Object[]) table.get(map)) {
            if (node != null) return "table=" + ((Object[]) table.get(map)).length + " bin=" + node.getClass().getSimpleName();
        }
        return "empty";
    }

    static String cached(String s) throws Exception {
        Field hash = String.class.getDeclaredField("hash");
        Field isZero = String.class.getDeclaredField("hashIsZero");
        hash.setAccessible(true);
        isZero.setAccessible(true);
        return "hash=" + hash.get(s) + " hashIsZero=" + isZero.get(s);
    }

    public static void main(String[] args) throws Exception {
        System.out.println("-- the formula");
        System.out.println("'A'*31+'a' = " + ('A' * 31 + 'a') + ", 'B'*31+'B' = " + ('B' * 31 + 'B'));
        System.out.println("Aa=" + "Aa".hashCode() + " BB=" + "BB".hashCode() + " equal? " + "Aa".equals("BB"));
        System.out.println("by hand matches hashCode: " + (hashByHand("hello, hash") == "hello, hash".hashCode()));

        System.out.println("-- 2^n collisions");
        System.out.println(colliding(3));
        List<String> big = colliding(10);
        System.out.println(big.size() + " strings, " + big.stream().distinct().count() + " distinct, "
                + big.stream().map(String::hashCode).distinct().count() + " distinct hash code");

        System.out.println("-- switch on colliding labels");
        System.out.println(label("Aa") + " " + label("BB") + " " + label("Ab"));

        System.out.println("-- one bin filling up");
        HashMap<SortableKey, Integer> growing = new HashMap<>();
        String previous = "";
        for (int i = 0; i < 12; i++) {
            growing.put(new SortableKey(colliding(4).get(i)), i);
            String now = firstBin(growing);
            if (!now.equals(previous)) System.out.println((i + 1) + " keys: " + now);
            previous = now;
        }

        System.out.println("-- 1024 lookups, all keys in one bin");
        System.out.println("Hashtable, chain:       " + lookupCost(new Hashtable<>(), PlainKey::new, big));
        System.out.println("HashMap, Comparable:    " + lookupCost(new HashMap<>(), SortableKey::new, big));
        System.out.println("HashMap, not Comparable: " + lookupCost(new HashMap<>(), PlainKey::new, big));

        System.out.println("-- the cached hash");
        String s = "hel".concat("lo");
        System.out.println("fresh:    " + cached(s));
        s.hashCode();
        System.out.println("hashed:   " + cached(s));
        String zero = "f5a5a6".concat("08");
        System.out.println("zero hash is " + zero.hashCode() + ", " + cached(zero));
    }
}
```

Output:

```text output
-- the formula
'A'*31+'a' = 2112, 'B'*31+'B' = 2112
Aa=2112 BB=2112 equal? false
by hand matches hashCode: true
-- 2^n collisions
[AaAaAa, AaAaBB, AaBBAa, AaBBBB, BBAaAa, BBAaBB, BBBBAa, BBBBBB]
1024 strings, 1024 distinct, 1 distinct hash code
-- switch on colliding labels
first second other
-- one bin filling up
1 keys: table=16 bin=Node
9 keys: table=32 bin=Node
10 keys: table=64 bin=Node
11 keys: table=64 bin=TreeNode
-- 1024 lookups, all keys in one bin
Hashtable, chain:       equals=524800 compareTo=0
HashMap, Comparable:    equals=10766 compareTo=8718
HashMap, not Comparable: equals=525823 compareTo=0
-- the cached hash
fresh:    hash=0 hashIsZero=false
hashed:   hash=99162322 hashIsZero=false
zero hash is 0, hash=0 hashIsZero=true
```

The same trick with a `switch`. The compiler has to cope with the fact that `case "Aa"` and `case "BB"` have the same hash, so it is worth a look at what javac 25 makes of this method:

```java
public class Switch {
    static String label(String s) {
        return switch (s) {
            case "Aa" -> "first";
            case "BB" -> "second";
            default -> "other";
        };
    }
}
```

```shell
javac Switch.java
javap -c -p Switch.class
```

The listing below is trimmed: the default constructor and the three result loads at the end are replaced by `...`, everything else is verbatim.

```text
Compiled from "Switch.java"
public class Switch {
  ...
  static java.lang.String label(java.lang.String);
    Code:
         0: aload_0
         1: astore_1
         2: iconst_m1
         3: istore_2
         4: aload_1
         5: invokevirtual #7                  // Method java/lang/String.hashCode:()I
         8: lookupswitch  { // 1
                    2112: 28
                 default: 53
            }
        28: aload_1
        29: ldc           #13                 // String BB
        31: invokevirtual #15                 // Method java/lang/String.equals:(Ljava/lang/Object;)Z
        34: ifeq          42
        37: iconst_1
        38: istore_2
        39: goto          53
        42: aload_1
        43: ldc           #19                 // String Aa
        45: invokevirtual #15                 // Method java/lang/String.equals:(Ljava/lang/Object;)Z
        48: ifeq          53
        51: iconst_0
        52: istore_2
        53: iload_2
        54: lookupswitch  { // 2
                       0: 80
                       1: 85
                 default: 90
            }
        ...
        92: areturn
}
```

## How it works

* **The formula is a polynomial,** and polynomials compose. `hash(p + x) = hash(p) * 31^len(x) + hash(x)` in `int` arithmetic, so a shared prefix or suffix changes nothing about whether two strings collide. That is the whole 2^n trick, and the `colliding` method is just a loop that doubles the list. The first two sections of the output show the formula worked by hand and eight strings from three blocks, and the third line shows that 1024 distinct strings really have one hash code.
* **Collisions are legal, so every hash table has a plan for them.** `HashMap` picks the bucket from the hash (`(table.length - 1) & (h ^ (h >>> 16))`), so equal hashes share a bucket no matter how big the table gets. Before Java 8 that bucket was a linked list and a lookup walked it. The `Hashtable` line still shows that world: 1024 lookups cost 524800 `equals` calls, which is exactly `1024 * 1025 / 2`, about 512 per lookup. Doubling the keys quadruples the work.
* **Hash flooding turns that into an attack.** Scott Crosby and Dan Wallach described algorithmic complexity attacks on hash tables in 2003. In 2011 Alexander Klink and Julian Wälde showed at 28C3 that web platforms (Java ones included) parsed request parameters into hash tables, so one POST body full of colliding parameter names could keep a server busy for a very long time. The `Aa`/`BB` recipe is the classic way to build such a body for Java.
* **JEP 180 (Java 8) gave `HashMap` a second line of defense:** a bin that gets too long is converted into a red-black tree. The [source](https://github.com/openjdk/jdk/blob/master/src/java.base/share/classes/java/util/HashMap.java) has two constants: `TREEIFY_THRESHOLD = 8` and `MIN_TREEIFY_CAPACITY = 64`. The "one bin filling up" section of the output shows what that means in practice. When the ninth key lands in a bin that already holds eight, `HashMap` first checks the table size. A table smaller than 64 is not treeified but resized instead, on the theory that a short table is the real problem: key 9 grows it from 16 to 32, key 10 from 32 to 64 (the keys stay together, because they have the same hash, so this helps nothing), and only key 11 turns the bin into `TreeNode`s.
* **The tree only helps keys it can order.** Ordering is by hash first, and our keys all have the same hash, so the tree falls back on `compareTo` if the key class implements `Comparable<itself>`. `String` does, and `SortableKey` copies that design: 1024 lookups cost 10766 `equals` calls and 8718 `compareTo` calls, roughly ten comparisons per lookup, which is log2(1024). `PlainKey` is not `Comparable`, and the numbers say what happens then: 525823 `equals` calls, no better than the linked list (the extra 1023 over the chain is the root, which `getNode` and `find` both compare for every key except the root itself). With equal hashes and no ordering, `TreeNode.find` has no way to choose a direction, so it searches both subtrees. The total does not even depend on the shape of the tree.
* **`switch` on a string is a hash switch plus `equals`.** javac does not trust the hash to be unique. In the listing, the first `lookupswitch` has one entry, 2112, for two case labels. Behind it sits an `equals` chain that checks `"BB"`, then `"Aa"`, and stores a small index in local variable 2. A second `lookupswitch` on that index jumps to the code of the chosen branch. A string with an unknown hash skips straight to `default`, and the output line `first second other` shows the colliding labels are told apart. This is javac 25's translation; the language specification only promises the behavior, and other compilers (or other javac versions) are free to emit something else.
* **`String` caches its hash.** The field `hash` starts at 0 and is filled by the first `hashCode()` call (fresh and hashed lines). That left a hole for years: a string whose hash is genuinely 0 looked like "not computed yet" and was recomputed on every call. Java 13 added a `hashIsZero` flag to close it, and the last line shows `"f5a5a608"`, a well-known string whose hash is 0, with the flag set. Reading these private fields needs `--add-opens java.base/java.lang=ALL-UNNAMED` and is only a peek at one JDK's implementation, not something to build on.

## Gotchas

* **The hash function cannot be randomized.** Python and Ruby salt string hashes per process. Java cannot, because `String.hashCode()` is specified in the Javadoc and programs rely on its exact values (the `switch` above compiles those values into class files). That is why the defense lives in `HashMap`, not in `String`.
* **Trees need `Comparable` keys, and your own key classes usually are not.** If a map is keyed by something an outsider controls and the key type has a weak or guessable `hashCode`, make it `Comparable<itself>`, or mix a per-process secret into the hash.
* **Trees fix the cost, not the exposure.** 1024 keys in one bin is still about ten comparisons per operation, where a healthy map needs about one. The practical defenses are the boring ones: cap the number of parameters or keys a single request may create, and validate input before it becomes a key.
* **Equal hashes say nothing about equality.** `"Aa".hashCode() == "BB".hashCode()` is `true` and `"Aa".equals("BB")` is `false`. A `hashCode` is only a bucket hint, so never use it as an identifier or as a key in a `Map<Integer, ...>`.
* **Other tables follow other rules.** `ConcurrentHashMap` also treeifies long bins, `HashSet` and `LinkedHashMap` inherit the behavior from `HashMap`, and `Hashtable` never changed. See [062](../07-puzzlers/062-collections-traps.md) for more traps in the collection classes.

## When to use it (and when not to)

As a trick, only for tests and demos. A colliding key set is a cheap way to unit test your own `equals`/`hashCode` pair under heavy collisions, to check that a container you wrote degrades gracefully, or to reproduce a performance bug that only appears when many keys share a bucket. Aiming it at a system you do not own is an attack, not a trick.

The knowledge, on the other hand, is production relevant: do not put untrusted input into a hash table without limits, make your own key types `Comparable` if they might be attacker-influenced, and remember that `hashCode()` is neither unique nor secret.

## Related

* [064 · String Traps](../07-puzzlers/064-string-traps.md)
* [066 · The Element That Vanished from the HashSet](../07-puzzlers/066-vanishing-hashset.md)
* [055 · The Integer Cache and Making 2 + 2 = 5](055-integer-cache-2-plus-2.md)

## Sources

* [JEP 180: Handle Frequent HashMap Collisions with Balanced Trees](https://openjdk.org/jeps/180) (Java 8)
* [`String.hashCode()` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/String.html#hashCode()), which specifies the formula
* Scott Crosby and Dan Wallach, [Denial of Service via Algorithmic Complexity Attacks](https://www.usenix.org/legacy/events/sec03/tech/full_papers/crosby/crosby.pdf) (USENIX Security 2003)
* Alexander Klink and Julian Wälde, [Effective Denial of Service attacks against web application platforms](https://events.ccc.de/congress/2011/Fahrplan/events/4680.en.html) (28C3, 2011)
* Heinz Kabutz, [Strings with Zero HashCode](https://www.javaspecialists.eu/archive/Issue277-Strings-with-Zero-HashCode.html), The Java Specialists' Newsletter 277 (2020)
