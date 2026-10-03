# 063 · ConcurrentModificationException and the One Case It Doesn't Fire

> Remove an element from a list while a for-each loop walks it and Java throws, unless it is the second-to-last element, in which case the loop just quietly stops early. A fail-fast iterator that sometimes fails to fail.

**Since:** Java 9 · **Category:** [Puzzlers and Gotchas](../README.md#puzzlers-and-gotchas) · **Level:** Beginner · **Verdict:** ✅ Production

## The puzzle

Everybody learns early that removing from an `ArrayList` inside a for-each loop throws `ConcurrentModificationException`. The program below tests that rule four times on a four-element list, once per victim. Then it tries a few more ways of touching a list mid-iteration, and finally four common fixes. Predict every line: which removals throw, which finish, and what is left in the list when they do.

```java run
import java.util.*;
import java.util.concurrent.CopyOnWriteArrayList;

public class FailFast {

    static List<String> crew() {
        return new ArrayList<>(List.of("Ada", "Grace", "Linus", "Barbara"));
    }

    static void removeDuringForEach(String victim) {
        List<String> names = crew();
        List<String> visited = new ArrayList<>();
        try {
            for (String name : names) {
                visited.add(name);
                if (name.equals(victim)) {
                    names.remove(name);
                }
            }
            System.out.printf("remove %-8s finished  visited=%s left=%s%n", victim, visited, names);
        } catch (ConcurrentModificationException e) {
            System.out.printf("remove %-8s CME       visited=%s%n", victim, visited);
        }
    }

    static void attempt(String label, Runnable action) {
        try {
            action.run();
            System.out.printf("%-34s fine%n", label);
        } catch (RuntimeException e) {
            System.out.printf("%-34s %s%n", label, e.getClass().getSimpleName());
        }
    }

    static List<String> withTwoLs() {
        return new ArrayList<>(List.of("Ada", "Grace", "Linus", "Lovelace"));
    }

    public static void main(String[] args) {
        System.out.println("-- 1. remove one name inside a for-each");
        for (String victim : crew()) {
            removeDuringForEach(victim);
        }

        System.out.println("-- 2. remove every name that starts with L");
        List<String> team = withTwoLs();
        for (String name : team) {
            if (name.startsWith("L")) team.remove(name);
        }
        System.out.println("for-each loop:   " + team);

        List<String> squad = new ArrayList<>(List.of("Ada", "Linus", "Lovelace", "Grace"));
        for (int i = 0; i < squad.size(); i++) {
            if (squad.get(i).startsWith("L")) squad.remove(i);
        }
        System.out.println("index loop:      " + squad);

        System.out.println("-- 3. other ways to touch a list mid-iteration");
        List<String> a = crew();
        attempt("forEach(lambda) removes Linus", () -> a.forEach(n -> { if (n.equals("Linus")) a.remove(n); }));
        List<String> b = crew();
        attempt("for-each + set(0, ...)", () -> { for (String n : b) b.set(0, n); });
        List<String> c = crew();
        attempt("for-each + sort(null)", () -> { for (String n : c) c.sort(null); });

        System.out.println("-- 4. fixes");
        List<String> viaIterator = withTwoLs();
        for (Iterator<String> it = viaIterator.iterator(); it.hasNext(); ) {
            if (it.next().startsWith("L")) it.remove();
        }
        System.out.println("Iterator.remove: " + viaIterator);

        List<String> viaRemoveIf = withTwoLs();
        viaRemoveIf.removeIf(n -> n.startsWith("L"));
        System.out.println("removeIf:        " + viaRemoveIf);

        List<String> viaCopy = withTwoLs();
        for (String name : new ArrayList<>(viaCopy)) {
            if (name.startsWith("L")) viaCopy.remove(name);
        }
        System.out.println("iterate a copy:  " + viaCopy);

        List<String> cow = new CopyOnWriteArrayList<>(withTwoLs());
        for (String name : cow) {
            if (name.startsWith("L")) cow.remove(name);
        }
        System.out.println("CopyOnWrite:     " + cow);
        attempt("CopyOnWrite iterator().remove()", () -> {
            Iterator<String> it = cow.iterator();
            it.next();
            it.remove();
        });
    }
}
```

## The answer

```text output
-- 1. remove one name inside a for-each
remove Ada      CME       visited=[Ada]
remove Grace    CME       visited=[Ada, Grace]
remove Linus    finished  visited=[Ada, Grace, Linus] left=[Ada, Grace, Barbara]
remove Barbara  CME       visited=[Ada, Grace, Linus, Barbara]
-- 2. remove every name that starts with L
for-each loop:   [Ada, Grace, Lovelace]
index loop:      [Ada, Lovelace, Grace]
-- 3. other ways to touch a list mid-iteration
forEach(lambda) removes Linus      ConcurrentModificationException
for-each + set(0, ...)             fine
for-each + sort(null)              ConcurrentModificationException
-- 4. fixes
Iterator.remove: [Ada, Grace]
removeIf:        [Ada, Grace]
iterate a copy:  [Ada, Grace]
CopyOnWrite:     [Ada, Grace]
CopyOnWrite iterator().remove()    UnsupportedOperationException
```

## Why

### Section 1: `hasNext` checks the size, only `next` checks for trouble

A for-each loop over a list is sugar for an iterator:

```java
for (Iterator<String> it = names.iterator(); it.hasNext(); ) {
    String name = it.next();
    ...
}
```

Here is what `ArrayList`'s iterator does with those two calls in JDK 25, trimmed:

```java
int cursor;                          // index of next element to return
int expectedModCount = modCount;

public boolean hasNext() {
    return cursor != size;
}

public E next() {
    checkForComodification();        // throws CME if modCount != expectedModCount
    ...
}
```

Every structural change (`add`, `remove`, `clear`, and as section 3 shows, `sort`) bumps the list's `modCount`. The iterator remembers the value it started with and compares it in `next()`. That is the whole fail-fast mechanism, and it has a hole: the check lives in `next()`, and `next()` is only called when `hasNext()` says there is more.

Removing `Linus` (index 2) happens when `cursor` is already 3. The list shrinks to size 3, `hasNext()` asks "is `3 != 3`?", gets `false`, and the loop ends normally. No `next()`, no check, no exception, and `Barbara` was never visited. For any other victim, `cursor` and `size` do not line up, so the loop calls `next()` once more and gets caught. Removing the *last* element throws too: `cursor` is 4, `size` is 3, `4 != 3` is `true`, and `next()` throws.

### Section 2: silently wrong is worse than loudly wrong

That hole is more than trivia. "Remove every name that starts with L" removes `Linus`, skips `Lovelace` because it moved into the slot the iterator had already passed, and finishes without a word. The index-based loop is the version people write to *avoid* the exception, and it has the same bug in a different spot: after `squad.remove(1)` shifts `Lovelace` down to index 1, `i++` moves on to index 2 and never looks at it. Neither loop throws. Both leave a name starting with L in the list.

### Section 3: not every path uses the same check

`ArrayList.forEach` does not use an iterator. It runs its own loop and checks `modCount` once more *after* the loop, so it catches the second-to-last case that the for-each loop misses. `set` is not a structural modification (the size does not change), so it never bumps `modCount` and never throws. `sort` does bump `modCount`, even though it keeps the size, because reordering under an iterator is just as confusing. The rule is not "changing the size throws"; it is "whatever this particular class counts as a structural change throws, next time somebody checks".

### Section 4: the fixes

* **`Iterator.remove()`** removes the element the iterator last returned and then resynchronizes: it moves `cursor` back and copies the new `modCount` into `expectedModCount`. It is the only way to remove *during* an explicit iteration.
* **`Collection.removeIf`** (Java 8) is the best answer for "remove everything that matches". `ArrayList` overrides it to evaluate the predicate over all elements first and then compact the array in one pass, which is also faster than repeated `remove` calls.
* **Iterating a copy** is simple and always correct, at the cost of copying the list.
* **`CopyOnWriteArrayList`** gives every iterator a snapshot of the array as it was when the iteration started. Removing during iteration is fine and the loop sees every original element. The price: every write copies the whole array, and the snapshot iterator does not support `remove()` at all, as the last line shows.

### The name is a lie, and the guarantee is weak

Not a single line in this program involves a second thread. "Concurrent" here means "while an iteration is in progress", and the Javadoc says so: a single thread that modifies a collection directly while iterating over it with a fail-fast iterator gets this exception. The opposite direction is worse. With real threads, `modCount` is a plain `int` field with no `volatile` and no locking, so another thread's changes may not be visible to the iterator at all (see [084](../09-concurrency/084-visibility-puzzler.md)). The exception Javadoc is blunt: fail-fast behavior "cannot be guaranteed", it is thrown "on a best-effort basis", and it "should be used only to detect bugs". An unsynchronized `ArrayList` shared between threads can throw a `ConcurrentModificationException`, an `ArrayIndexOutOfBoundsException`, lose elements, or appear to work, depending on timing.

## Gotchas

* **`HashMap` iterators are fail-fast too**, with the same "check in `next()`" design. To remove entries while iterating, use `map.entrySet().removeIf(...)`, `map.values().removeIf(...)` or the entry set iterator's `remove()`.
* **`subList` views throw CME** when the parent list changes structurally behind their back. See [062](062-collections-traps.md).
* **`ConcurrentHashMap` and the other `java.util.concurrent` collections never throw CME.** Their iterators are *weakly consistent*: they may or may not reflect changes made after the iterator was created, and they never fail. That is a different contract, not a stronger one.
* **`Collections.synchronizedList` does not protect iteration.** Each method call is synchronized, but a loop is many calls. Its Javadoc tells you to hold the list's lock for the whole iteration yourself.
* **The holes depend on the class.** `LinkedList`'s iterator tests `nextIndex < size` instead of `cursor != size`, so with a `LinkedList` removing the *last* element escapes as well: on JDK 25, removing `Barbara` from a `LinkedList` this way finishes quietly and leaves `[Ada, Grace, Linus]`. The exact set of "lucky" cases is an implementation detail, which is one more reason not to rely on any of them.

## How to stay safe

* Never call `list.remove` or `list.add` inside a for-each loop over the same list, even if it "works" in your test. It works for the second-to-last element, and only for that one.
* Use `removeIf` for filtering in place, `Iterator.remove` when you need more logic per element, and a stream (`filter(...).toList()`) when a new list is fine.
* Treat CME as a bug report, never as control flow. Catching it and retrying is a race condition with extra steps.
* Share collections between threads only through the concurrent collections or proper locking. The fail-fast check is a debugging aid for single-threaded mistakes, not a thread-safety mechanism.

## Related

* [062 · Collection Traps](062-collections-traps.md)
* [072 · Map Power Idioms: merge, compute and Friends](../08-streams-collections/072-map-idioms.md)
* [083 · The Starting Gun: Testing Race Conditions](../09-concurrency/083-starting-gun.md)
* [084 · The Loop That Never Ends: volatile and the Memory Model](../09-concurrency/084-visibility-puzzler.md)

## Sources

* [`java.util.ConcurrentModificationException` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/ConcurrentModificationException.html)
* [`java.util.ArrayList` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/ArrayList.html), the paragraph on fail-fast iterators
* [`java.util.concurrent.CopyOnWriteArrayList` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/CopyOnWriteArrayList.html)
* [`ArrayList.java` in the OpenJDK repository](https://github.com/openjdk/jdk/blob/master/src/java.base/share/classes/java/util/ArrayList.java), the `Itr` inner class
