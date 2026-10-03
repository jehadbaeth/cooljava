# 039 · Type Erasure Puzzlers and Generic Arrays

> `new T[n]` does not compile, `Object[] a = new String[1]` does, and the gap between the two is where a `ClassCastException` on a line with no cast comes from. Arrays remember their element type, generics forget theirs, and Java makes the two meet only on its own terms.

**Since:** Java 16 · **Category:** [Generics and Type System Wizardry](../README.md#generics-and-type-system-wizardry) · **Level:** Advanced · **Verdict:** ✅ Production

## The problem

Sooner or later everyone writes `new T[10]` inside a generic class and meets this:

```java compile-fail
public class GenericArray {
    static <T> T[] makeArray(int length) {
        return new T[length];
    }

    public static void main(String[] args) {}
}
```

```text compile-error
GenericArray.java:3: error: generic array creation
        return new T[length];
               ^
1 error
```

The message reads like an arbitrary restriction. It is not. It plugs a hole between two type systems that disagree about *when* types are checked:

| | Arrays | Generics |
|---|---|---|
| Variance | covariant: a `String[]` is an `Object[]` | invariant: a `List<String>` is not a `List<Object>` |
| Element type at runtime | known (reified) | erased |
| Checked | at runtime, on every store (`ArrayStoreException`) | at compile time only |

Each system is consistent on its own. Together they are not, and the rest of this document is what happens at the seam: `ArrayStoreException`, exceptions that point at innocent lines, overloads that collide, and `instanceof` tests the compiler refuses.

## The trick

There is no trick to *make* `new T[n]` work. The skill is knowing the four honest ways around it, and recognizing the one dishonest way (`(T[]) new Object[n]`) so that it does not leak:

* **Do not use an array.** `List<T>` is invariant and checked by the compiler, and it is what [Effective Java](https://www.informit.com/articles/article.aspx?p=2861454&seqNum=7) recommends first.
* **Let the caller supply the array.** `list.toArray(String[]::new)` (collections, since Java 11) and `stream.toArray(String[]::new)` take an `IntFunction<T[]>`. Your own classes can accept one too (`TypedBox` below).
* **Take a `Class<T>` token** and call `Array.newInstance(type, length)`, which builds an array whose runtime type really is `T[]`.
* **Keep the array private and typed `Object[]`**, and cast single elements on the way out. That is how `ArrayList` stores its elements.

The dishonest way, `(T[]) new Object[n]`, compiles with an unchecked warning and works until the array escapes. The full example shows it exploding at the caller, and it also builds the exact hole that the compiler's ban is there to prevent.

## Full example

```java run
import java.lang.reflect.Array;
import java.util.*;
import java.util.function.IntFunction;

public class ErasureDemo {

    // ---------- Two ways to hold a T[] ----------

    static class LooseBox<T> {                      // (T[]) new Object[n]: javac cannot check this cast
        private final T[] slots;
        @SuppressWarnings("unchecked")
        LooseBox(int size) { slots = (T[]) new Object[size]; }
        T[] slots() { return slots; }
    }

    static class TypedBox<T> {                      // the caller hands over the array factory: no unchecked cast at all
        private final T[] slots;
        TypedBox(IntFunction<T[]> factory, int size) { slots = factory.apply(size); }
        T[] slots() { return slots; }
    }

    @SuppressWarnings("unchecked")
    static <T> T[] newArray(Class<T> type, int length) {      // a Class<T> token is enough to build a real T[]
        return (T[]) Array.newInstance(type, length);
    }

    // ---------- Generic varargs: the array is created at the call site, where T is already gone ----------

    @SuppressWarnings("unchecked")
    static <T> T[] toArray(T... args) { return args; }

    @SuppressWarnings("unchecked")
    static <T> T[] pickTwo(T a, T b, T c) { return toArray(a, b); }

    @SafeVarargs                                    // honest: the array is only read, never stored or returned
    static <T> List<T> listOf(T... items) { return new ArrayList<>(Arrays.asList(items)); }

    public static void main(String[] args) {
        System.out.println("1. arrays are checked at runtime");
        Object[] objects = new String[1];           // legal: String[] is an Object[]
        try {
            objects[0] = 42;
        } catch (ArrayStoreException e) {
            System.out.println("   " + e);
        }

        System.out.println("2. what a generic array would allow");
        @SuppressWarnings("unchecked")
        List<String>[] lists = (List<String>[]) new List[1];    // new List<String>[1] is a compile error; this cast sneaks past it
        Object[] asObjects = lists;
        asObjects[0] = List.of(42);                 // the store check sees a List, and cannot tell a List<Integer>
        try {
            String first = lists[0].get(0);
            System.out.println("   " + first);
        } catch (ClassCastException e) {
            System.out.println("   the pollution surfaces at the read: ClassCastException");
        }

        System.out.println("3. getting a real String[]");
        List<String> names = List.of("Ada", "Grace");
        String[] viaFactory = names.toArray(String[]::new);
        System.out.println("   toArray(String[]::new):  " + viaFactory.getClass().getSimpleName() + " " + Arrays.toString(viaFactory));
        String[] viaToken = newArray(String.class, 2);
        System.out.println("   Array.newInstance:       " + viaToken.getClass().getSimpleName() + " of length " + viaToken.length);
        String[] fromTyped = new TypedBox<String>(String[]::new, 2).slots();
        System.out.println("   TypedBox<String>.slots:  " + fromTyped.getClass().getSimpleName());
        try {
            String[] fromLoose = new LooseBox<String>(2).slots();
            System.out.println("   " + fromLoose.length);
        } catch (ClassCastException e) {
            System.out.println("   LooseBox<String>.slots:  " + e.getMessage());
        }

        System.out.println("4. generic varargs and heap pollution");
        try {
            String[] picked = pickTwo("Good", "Fast", "Cheap");
            System.out.println("   " + Arrays.toString(picked));
        } catch (ClassCastException e) {
            System.out.println("   pickTwo returned an Object[]: ClassCastException at the call site");
        }
        List<String> safe = listOf("a", "b");
        System.out.println("   listOf: " + safe);

        System.out.println("5. instanceof and erasure");
        Collection<String> collection = new ArrayList<>(List.of("Ada"));
        if (collection instanceof List<String> list) {
            System.out.println("   Collection<String> instanceof List<String> compiles: " + list.get(0));
        }
        Object anything = collection;
        if (anything instanceof List<?> list) {
            System.out.println("   Object instanceof List<?> compiles, the element type is unknown: " + list.size() + " element");
        }
    }
}
```

Output:

```text output
1. arrays are checked at runtime
   java.lang.ArrayStoreException: java.lang.Integer
2. what a generic array would allow
   the pollution surfaces at the read: ClassCastException
3. getting a real String[]
   toArray(String[]::new):  String[] [Ada, Grace]
   Array.newInstance:       String[] of length 2
   TypedBox<String>.slots:  String[]
   LooseBox<String>.slots:  class [Ljava.lang.Object; cannot be cast to class [Ljava.lang.String; ([Ljava.lang.Object; and [Ljava.lang.String; are in module java.base of loader 'bootstrap')
4. generic varargs and heap pollution
   pickTwo returned an Object[]: ClassCastException at the call site
   listOf: [a, b]
5. instanceof and erasure
   Collection<String> instanceof List<String> compiles: Ada
   Object instanceof List<?> compiles, the element type is unknown: 1 element
```

Two more compile errors belong to this family. Both are about erasure: after it, `List<String>` and `List<Integer>` are the same type, `List`.

```java compile-fail
import java.util.List;

public class ErasureClash {
    static void print(List<String> strings) {}
    static void print(List<Integer> numbers) {}

    public static void main(String[] args) {}
}
```

```text compile-error
ErasureClash.java:5: error: name clash: print(List<Integer>) and print(List<String>) have the same erasure
    static void print(List<Integer> numbers) {}
                ^
1 error
```

```java compile-fail
import java.util.List;

public class NotSafelyCast {
    public static void main(String[] args) {
        Object anything = List.of(1, 2, 3);
        if (anything instanceof List<String> strings) {
            System.out.println(strings.get(0).length());
        }
    }
}
```

```text compile-error
NotSafelyCast.java:6: error: Object cannot be safely cast to List<String>
        if (anything instanceof List<String> strings) {
            ^
1 error
```

## How it works

* **Section 1: the array store check.** `Object[] objects = new String[1]` is legal because arrays are covariant (a leftover from before generics existed, when a method like `Arrays.sort(Object[])` could only accept every kind of array by way of covariance). The price is a check on every store: the array knows it is a `String[]`, so storing an `Integer` throws `ArrayStoreException`, and the message is the class of the rejected value.
* **Section 2: why `new List<String>[1]` is banned.** The store check compares the value with the array's *runtime* element type, and for `List<String>[]` that type is plain `List`. A `List<Integer>` passes the check, lands in an array that claims to hold string lists, and the damage shows up later, at the read, as `ClassCastException`. Heap pollution always surfaces away from its cause. The language rule is that you may only create arrays of *reifiable* types (JLS §4.7): `String[]`, `List[]` and `List<?>[]` are fine, `List<String>[]` and `T[]` are not. The unchecked cast `(List<String>[]) new List[1]` sneaks past the rule, and the output shows what it buys you.
* **Section 3: where the missing cast goes.** `(T[]) new Object[n]` erases to `(Object[]) new Object[n]`, which is a no-op, so the cast cannot fail inside the class. At the call site, where `T` is known to be `String`, javac inserts `checkcast String[]` on the returned array, and that is where it fails, with a message that names `[Ljava.lang.Object;` and `[Ljava.lang.String;`. The throwing line is the caller's, the bug is in `LooseBox`. `TypedBox` has no unchecked cast at all, and `newArray` has one that is justified for reference types, because `Array.newInstance(type, n)` really returns a `T[]`. The default `Collection.toArray(IntFunction)` is just `toArray(generator.apply(0))`.
* **Section 4: generic varargs.** A varargs call creates an array of the declared component type at the *call site*. Inside `pickTwo`, `T` is erased, so `toArray(a, b)` builds an `Object[]`. It travels back through `toArray` and `pickTwo` untouched, and main's hidden `checkcast String[]` rejects it. This is the `pickTwo` example from Effective Java (Item 32), and javac warns twice about it, which `@SuppressWarnings("unchecked")` hides in the demo: `Possible heap pollution from parameterized vararg type T` at the declaration, and `unchecked generic array creation for varargs parameter of type T[]` at the call.
* **`@SafeVarargs` is a promise, not a check.** It says: this method does not store anything into the varargs array and does not let it escape. `listOf` honors that, since it copies the elements into a new list. javac accepts the annotation on static methods, constructors, `final` instance methods and (since Java 9) `private` instance methods, and rejects it on any other instance method (`Invalid SafeVarargs annotation. Instance method <T>bad(T...) is neither final nor private.`). `List.of(E...)` and `Arrays.asList(T...)` carry it. The demo's `toArray` must not carry it, because it returns the array.
* **Section 5: `instanceof` has no runtime generics.** At runtime a `List<String>` test can only check for `List`. Before Java 16, `instanceof` accepted only reifiable types such as `List<?>`. Since Java 16 (JEP 394) a parameterized type also compiles when the cast is statically safe, which is the case for `Collection<String>` to `List<String>`: the type argument is already known. From `Object` it is not, and javac says `Object cannot be safely cast to List<String>`. The honest test is `instanceof List<?>`, followed by checking elements.
* **The overload clash is erasure in the class file.** `print(List<String>)` and `print(List<Integer>)` both compile to `print(List)`, so the class would contain two methods with one signature (JLS §8.4.2 calls this "same erasure"). Rename them, or change something else in the parameter list.

## Gotchas

* **The exception is thrown where the value is used, not where it went wrong.** Heap pollution is quiet. A `ClassCastException` in a method without any cast, or on a plain `String s = list.get(0)`, usually means somebody upstream lied with an unchecked cast, a raw type or generic varargs. Read the stack trace towards the cause and look for `@SuppressWarnings("unchecked")`.
* **Do not return `T[]` from a method that built it from erased pieces.** Return `List<T>`, take an `IntFunction<T[]>` or a `Class<T>`, or return `Object[]` and let the caller decide.
* **`toArray(new String[0])` is fine, and so is the method reference.** Old advice said to pass an array of the right size to avoid an allocation. [Shipilev's measurements](https://shipilev.net/blog/2016/arrays-wisdom-ancients/) show the zero-length version is at least as fast, and the method reference form (`toArray(String[]::new)`) says the same thing without a throwaway array.
* **`List<?>[]` and `Class<?>[]` are legal to create**, because an unbounded wildcard is reifiable. Declaring a variable of type `List<String>[]` is legal too. Only the creation is banned.
* **`Map.Entry<K, V>[]` is the same story.** The usual workaround is a `List<Map.Entry<K, V>>`.
* **Covariance bites your own methods too.** A method that accepts `Object[]` and stores into it compiles, and throws `ArrayStoreException` for any caller that passes a more specific array. Treat array parameters as read-only.

## When to use it (and when not to)

This is knowledge, not a tool, and it earns its place in production code: it is the difference between a stack trace you can read and one that looks like a JVM bug. The practical rules are short. Prefer `List<T>` to `T[]` in APIs. When an array is unavoidable (varargs, interop, `toArray`), build it from a `Class<T>` or an `IntFunction<T[]>`. When writing your own collection, store elements in an `Object[]` and cast on read, as the JDK does. Use `@SafeVarargs` only on methods that really only read their varargs, and make them `static` or `final`.

If you meet an unfamiliar `@SuppressWarnings("unchecked")`, treat it as a place where the compiler stopped helping, and make sure the comment next to it says why it is safe.

## Related

* [032 · Super Type Tokens: Capturing Generic Types at Runtime](032-super-type-tokens.md), for how `List<String>` survives erasure in a subclass signature
* [033 · The Type-Safe Heterogeneous Container](033-heterogeneous-container.md), the `Class<T>` token used for a safe `cast`
* [035 · PECS and Wildcard Capture](035-pecs-wildcard-capture.md), generics invariance and how wildcards relax it
* [036 · Sneaky Throws: Checked Exceptions Without the Paperwork](036-sneaky-throws.md), another lie that erasure makes possible

## Sources

* Joshua Bloch, *Effective Java*, 3rd edition: Item 28 (prefer lists to arrays) and [Item 32 (combine generics and varargs judiciously)](https://www.informit.com/articles/article.aspx?p=2861454&seqNum=7), which has the `pickTwo` example
* [JLS §4.7: Reifiable Types](https://docs.oracle.com/javase/specs/jls/se25/html/jls-4.html#jls-4.7) (and §4.6 on type erasure, §8.4.2 for the "same erasure" rule)
* [`@SafeVarargs`](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/SafeVarargs.html) in the Java 25 API docs
* The Java Tutorials, [Restrictions on Generics](https://docs.oracle.com/javase/tutorial/java/generics/restrictions.html)
* [JEP 394: Pattern Matching for instanceof](https://openjdk.org/jeps/394)
