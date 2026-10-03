# 030 · Phantom Types: Let the Compiler Track State

> A type parameter that is never used at runtime, and that is exactly the point: it lets javac reject whole classes of bugs for free.

**Since:** Java 17 · **Category:** [Generics and Type System Wizardry](../README.md#generics-and-type-system-wizardry) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

Lots of values share a runtime representation but must never be mixed up:

* a `long` user id and a `long` order id,
* a thrust impulse in newton seconds and one in pound-force seconds,
* a connection that is open and one that is already closed.

The classic failure is famous. In 1999 NASA lost the Mars Climate Orbiter because one piece of ground software produced impulse values in pound-force seconds while another consumed them as newton seconds. Both were just numbers.

## The trick

Add a type parameter that **no field uses**. It exists only for the compiler:

```java
record Id<T>(long value) {}             // T is never stored anywhere

Order findOrder(Id<Order> id) { ... }

Id<User> userId = new Id<>(42);
findOrder(userId);                      // does not compile
```

At runtime `Id<User>` and `Id<Order>` are the same class holding the same `long` (erasure removes `T`), so there is **zero runtime cost**. At compile time they are different types. That unused parameter is the *phantom*.

The same idea tracks **state**. Make the phantom one of a closed set of marker types, and write transitions as methods that accept only the right state:

```java
static Door<Closed> close(Door<Open> door)   { ... }
static Door<Locked> lock(Door<Closed> door)  { ... }
```

Now "lock an open door" is not a runtime check you might forget; it is a program that does not compile.

## Full example

```java run
import java.util.*;

public class PhantomDemo {

    // 1. Typed ids: same representation, different types.
    record Id<T>(long value) {
        @Override public String toString() { return "#" + value; }
    }
    record User(Id<User> id, String name) {}
    record Order(Id<Order> id, Id<User> buyer, String item) {}

    static final Map<Long, Order> ORDERS = new HashMap<>();

    static Optional<Order> findOrder(Id<Order> id) { return Optional.ofNullable(ORDERS.get(id.value())); }

    // 2. Units of measure as phantom types.
    sealed interface Unit permits NewtonSeconds, PoundForceSeconds {}
    enum NewtonSeconds implements Unit {}
    enum PoundForceSeconds implements Unit {}

    record Impulse<U extends Unit>(double amount) {
        static Impulse<NewtonSeconds> newtonSeconds(double v) { return new Impulse<>(v); }
        static Impulse<PoundForceSeconds> poundForceSeconds(double v) { return new Impulse<>(v); }

        // Only impulses of the *same* unit can be added.
        Impulse<U> plus(Impulse<U> other) { return new Impulse<>(amount + other.amount); }
    }

    // The one and only door between the two worlds is explicit and named.
    static Impulse<NewtonSeconds> toSi(Impulse<PoundForceSeconds> i) {
        return Impulse.newtonSeconds(i.amount() * 4.448222);
    }

    // 3. State tracking: a door's state lives in its type.
    sealed interface DoorState permits Open, Closed, Locked {}
    enum Open implements DoorState {}       // enums with no constants: types that can never be instantiated
    enum Closed implements DoorState {}
    enum Locked implements DoorState {}

    record Door<S extends DoorState>(String name) {
        static Door<Closed> install(String name) { return new Door<>(name); }
    }

    static Door<Open> open(Door<Closed> d)   { System.out.println("  " + d.name() + ": open");   return new Door<>(d.name()); }
    static Door<Closed> close(Door<Open> d)  { System.out.println("  " + d.name() + ": close");  return new Door<>(d.name()); }
    static Door<Locked> lock(Door<Closed> d) { System.out.println("  " + d.name() + ": lock");   return new Door<>(d.name()); }
    static Door<Closed> unlock(Door<Locked> d) { System.out.println("  " + d.name() + ": unlock"); return new Door<>(d.name()); }

    public static void main(String[] args) {
        var ada = new User(new Id<>(1), "Ada");
        var order = new Order(new Id<>(100), ada.id(), "telescope");
        ORDERS.put(order.id().value(), order);

        System.out.println(findOrder(order.id()));
        // findOrder(ada.id());   <- would not compile: Id<User> is not Id<Order>

        var thrusterA = Impulse.newtonSeconds(120.0);
        var thrusterB = Impulse.poundForceSeconds(10.0);
        // thrusterA.plus(thrusterB);   <- would not compile: different units
        System.out.printf("total impulse: %.2f N*s%n", thrusterA.plus(toSi(thrusterB)).amount());

        System.out.println("door lifecycle:");
        Door<Closed> front = Door.install("front");
        Door<Locked> locked = lock(close(open(front)));
        // open(locked);   <- would not compile: a Locked door must be unlocked first
        open(unlock(locked));

        // Erasure: at runtime the phantom is gone, and it costs nothing.
        System.out.println("same class at runtime? "
                + (new Id<User>(1).getClass() == new Id<Order>(1).getClass()));
        System.out.println("equal at runtime?      " + new Id<User>(7).equals(new Id<Order>(7)));
    }
}
```

Output:

```text output
Optional[Order[id=#100, buyer=#1, item=telescope]]
total impulse: 164.48 N*s
door lifecycle:
  front: open
  front: close
  front: lock
  front: unlock
  front: open
same class at runtime? true
equal at runtime?      true
```

And here is what javac says when you try to open a locked door:

```java compile-fail
public class LockedDoor {
    sealed interface DoorState permits Closed, Locked {}
    enum Closed implements DoorState {}
    enum Locked implements DoorState {}
    record Door<S extends DoorState>(String name) {}

    static Door<Closed> open(Door<Closed> d) { return d; }

    public static void main(String[] args) {
        Door<Locked> vault = new Door<>("vault");
        open(vault);
    }
}
```

```text compile-error
LockedDoor.java:11: error: incompatible types: Door<Locked> cannot be converted to Door<Closed>
        open(vault);
             ^
Note: Some messages have been simplified; recompile with -Xdiags:verbose to get full output
1 error
```

## How it works

* **Erasure is the enabler.** Generic type arguments are checked by javac and then erased, so `Id<User>` and `Id<Order>` compile to the same class with the same `long` field. That is also why `equals` returns `true` at runtime: the phantom is a compile-time fact only.
* **Empty enums as marker types.** `enum Open implements DoorState {}` declares a type with no instances at all. Nobody can accidentally create an `Open` value, which is exactly what you want for a type that should only ever appear inside angle brackets. A `final class` with a private constructor works too.
* **`sealed` closes the set of states**, so nobody can invent `Door<Ajar>` from outside.
* **Transitions are plain static methods.** Java cannot specialize an *instance* method on the receiver's type argument (no `close()` that only exists on `Door<Open>`), so either use static functions as above, or switch to one interface per state as in the [step builder](../02-patterns/013-step-builder.md).
* **Constructors stay controlled.** `Door.install` is the only sanctioned way in, and it always starts `Closed`. In real code make the record's canonical constructor unreachable from outside by making `Door` a final class with a private constructor instead.

## Gotchas

* **Raw types and unchecked casts bypass everything.** `(Id<Order>) (Id) userId` compiles with a warning. Phantom types protect honest code, not adversarial code.
* **`var` and diamond inference can pick the "wrong" phantom silently** if a method is generic in it. Keep factory methods specific (`newtonSeconds`, not `of(double)`).
* **Runtime equality ignores the phantom.** If ids of different entity types end up in one `Set<Id<?>>`, `#7` user and `#7` order collide. Store a `Class<T>` alongside if that matters (now it is no longer purely phantom, but still type safe).
* **Serialization frameworks see only the erased type.** Jackson will happily deserialize JSON into an `Id<Whatever>`. Validate at the boundary.

## When to use it (and when not to)

Typed ids are a cheap, high-value habit in any codebase with more than a handful of entities: they turn "passed the wrong id" from a production incident into a red squiggle. Units of measure pay off whenever two units coexist in one system (aerospace, finance with currencies, physics). State tracking is great for small lifecycles (builder stages, open/closed resources, unauthenticated/authenticated sessions) but gets unwieldy beyond four or five states. At that point a runtime [state machine](../02-patterns/016-state-machines.md) is easier to read.

## Related

* [013 · Step Builder: Compile-Time Required Fields](../02-patterns/013-step-builder.md)
* [016 · State Machines with Enums and Sealed Types](../02-patterns/016-state-machines.md)
* [031 · Self-Bounded Generics for Inheritable Builders](031-self-bounded-generics.md)
* [039 · Type Erasure Puzzlers and Generic Arrays](039-erasure-and-arrays.md)

## Sources

* [Mars Climate Orbiter](https://en.wikipedia.org/wiki/Mars_Climate_Orbiter), Wikipedia, which summarizes the 1999 mishap board findings on the unit mismatch
* gekkio, [Increased compile-time safety with phantom types](https://gekkio.fi/blog/2013/increased-compile-time-safety-with-phantom-types/)
* [JLS §4.6: Type Erasure](https://docs.oracle.com/javase/specs/jls/se25/html/jls-4.html#jls-4.6)
