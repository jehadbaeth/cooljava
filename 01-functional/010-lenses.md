# 010 · Lenses: Deep Updates on Immutable Records

> A getter and a wither, packaged as one value, compose like functions. "Raise the orbit of the satellite of this mission by 50 km" becomes one line instead of three nested constructor calls.

**Since:** Java 16 · **Category:** [Functional Programming](../README.md#functional-programming) · **Level:** Advanced · **Verdict:** ⚠️ Situational

## The problem

Immutable records are great until they nest. Changing one leaf means rebuilding every record on the path from the root, and copying all the siblings along the way:

```java
Satellite sat = mission.satellite();
Mission raised = new Mission(mission.name(),
        new Satellite(sat.id(),
                new Orbit(sat.orbit().altitudeKm() + 50, sat.orbit().inclinationDeg()),
                sat.instruments()));
```

Three levels, seven components to spell out, and one `+ 50` hiding in the middle. Withers (see [014](../02-patterns/014-record-withers.md)) shorten each step but not the nesting:

```java
Mission raised = mission.withSatellite(sat.withOrbit(sat.orbit().withAltitudeKm(sat.orbit().altitudeKm() + 50)));
```

Now every update has to spell out the whole path twice: once to read the old value, once to write the new one. Add a fourth level and you add a fourth `with` and a fourth `.orbit()`-style hop. Mutable objects never had this problem (`mission.satellite.orbit.altitudeKm += 50`), which is one reason people give up on immutability.

## The trick

A **lens** is a first-class "path to a part". It knows how to read a part `A` out of a whole `S`, and how to produce a copy of the whole with that part replaced:

```java
record Lens<S, A>(Function<S, A> getter, BiFunction<S, A, S> setter) {
    A get(S whole)                    { return getter.apply(whole); }
    S set(S whole, A part)            { return setter.apply(whole, part); }
    S modify(S whole, UnaryOperator<A> f) { return set(whole, f.apply(get(whole))); }
}
```

A getter is just the record accessor, and a setter is just the wither you would write anyway. The payoff is that two lenses **compose**: a lens from `Mission` to `Satellite` and a lens from `Satellite` to `Orbit` make a lens from `Mission` to `Orbit`.

```java
<B> Lens<S, B> andThen(Lens<A, B> inner) {
    return new Lens<>(
            whole -> inner.get(get(whole)),
            (whole, b) -> set(whole, inner.set(get(whole), b)));
}
```

The setter reads: zoom in with the outer getter, replace the part with the inner lens, put the result back with the outer setter. Compose once, name the result, and every deep update is `altitude.modify(mission, km -> km + 50)`.

## Full example

Each record carries its own lens constants, built from its accessor and its wither. The main method compares the lens against hand-written constructors and withers, checks the three lens laws with record equality (the same trick as the [Maybe monad](001-maybe-monad.md)), and shows a lens that breaks a law. The pattern works on any Java version; this example uses records.

```java run
import java.util.*;
import java.util.function.*;

public class LensDemo {

    /** Focus on one part A of a whole S: read it, or get a copy of S with it replaced. */
    record Lens<S, A>(Function<S, A> getter, BiFunction<S, A, S> setter) {

        A get(S whole) { return getter.apply(whole); }
        S set(S whole, A part) { return setter.apply(whole, part); }
        S modify(S whole, UnaryOperator<A> f) { return set(whole, f.apply(get(whole))); }

        /** The update as a value: store it, pass it around, apply it later. */
        UnaryOperator<S> over(UnaryOperator<A> f) { return whole -> modify(whole, f); }

        <B> Lens<S, B> andThen(Lens<A, B> inner) {
            return new Lens<>(
                    whole -> inner.get(get(whole)),
                    (whole, b) -> set(whole, inner.set(get(whole), b)));
        }

        /** Focus on one list element. Partial: it throws when the index is out of range. */
        static <A> Lens<List<A>, A> at(int index) {
            return new Lens<>(
                    list -> list.get(index),
                    (list, a) -> {
                        List<A> copy = new ArrayList<>(list);
                        copy.set(index, a);
                        return List.copyOf(copy);
                    });
        }
    }

    record Instrument(String name, double massKg) {
        static final Lens<Instrument, Double> MASS_KG = new Lens<>(Instrument::massKg, Instrument::withMassKg);
        Instrument withMassKg(double v) { return new Instrument(name, v); }
    }

    record Orbit(double altitudeKm, double inclinationDeg) {
        Orbit {
            if (altitudeKm <= 0) throw new IllegalArgumentException("altitude must be positive, was " + altitudeKm);
        }
        static final Lens<Orbit, Double> ALTITUDE_KM = new Lens<>(Orbit::altitudeKm, Orbit::withAltitudeKm);
        Orbit withAltitudeKm(double v) { return new Orbit(v, inclinationDeg); }
    }

    record Satellite(String id, Orbit orbit, List<Instrument> instruments) {
        static final Lens<Satellite, Orbit> ORBIT = new Lens<>(Satellite::orbit, Satellite::withOrbit);
        static final Lens<Satellite, List<Instrument>> INSTRUMENTS =
                new Lens<>(Satellite::instruments, Satellite::withInstruments);
        Satellite withOrbit(Orbit v) { return new Satellite(id, v, instruments); }
        Satellite withInstruments(List<Instrument> v) { return new Satellite(id, orbit, v); }
    }

    record Mission(String name, Satellite satellite) {
        static final Lens<Mission, String> NAME = new Lens<>(Mission::name, Mission::withName);
        static final Lens<Mission, Satellite> SATELLITE = new Lens<>(Mission::satellite, Mission::withSatellite);
        Mission withName(String v) { return new Mission(v, satellite); }
        Mission withSatellite(Satellite v) { return new Mission(name, v); }
    }

    /** The three lens laws, checked with record equality. */
    static <S, A> void checkLaws(String label, Lens<S, A> lens, S whole, A first, A second) {
        boolean getSet = lens.set(whole, lens.get(whole)).equals(whole);
        boolean setGet = lens.get(lens.set(whole, first)).equals(first);
        boolean setSet = lens.set(lens.set(whole, first), second).equals(lens.set(whole, second));
        System.out.printf("%-26s get-set=%b set-get=%b set-set=%b%n", label, getSet, setGet, setSet);
    }

    public static void main(String[] args) {
        var mission = new Mission("Sentinel", new Satellite("S-1", new Orbit(700, 98.2),
                List.of(new Instrument("radar", 120), new Instrument("camera", 85))));

        // Composition: Mission -> Satellite -> Orbit -> altitude, and Mission -> ... -> first instrument's mass.
        var altitude = Mission.SATELLITE.andThen(Satellite.ORBIT).andThen(Orbit.ALTITUDE_KM);
        var firstMass = Mission.SATELLITE.andThen(Satellite.INSTRUMENTS)
                .andThen(Lens.at(0)).andThen(Instrument.MASS_KG);

        // 1. One line with a lens, versus constructors and chained withers.
        Mission raised = altitude.modify(mission, km -> km + 50);
        Satellite sat = mission.satellite();
        Mission viaConstructors = new Mission(mission.name(),
                new Satellite(sat.id(),
                        new Orbit(sat.orbit().altitudeKm() + 50, sat.orbit().inclinationDeg()),
                        sat.instruments()));
        Mission viaWithers = mission.withSatellite(
                sat.withOrbit(sat.orbit().withAltitudeKm(sat.orbit().altitudeKm() + 50)));
        System.out.println(raised);
        System.out.println("same as constructors: " + raised.equals(viaConstructors)
                + ", same as withers: " + raised.equals(viaWithers));
        System.out.println("original untouched: " + altitude.get(mission) + " km");
        System.out.println("siblings shared, not copied: "
                + (raised.satellite().instruments() == mission.satellite().instruments()));

        // 2. Updates are values: build a plan, apply it later.
        List<UnaryOperator<Mission>> plan = List.of(
                altitude.over(km -> km + 50),
                Mission.NAME.over(String::toUpperCase),
                firstMass.over(kg -> kg - 12));
        Mission updated = mission;
        for (UnaryOperator<Mission> step : plan) updated = step.apply(updated);
        System.out.println(updated.name() + " at " + altitude.get(updated) + " km, first instrument "
                + firstMass.get(updated) + " kg");

        // 3. The laws. A lens that normalizes its input breaks set-get.
        Lens<Orbit, Double> clamped = new Lens<>(Orbit::altitudeKm,
                (orbit, km) -> orbit.withAltitudeKm(Math.max(160, km)));
        checkLaws("composed altitude", altitude, mission, 800.0, 900.0);
        checkLaws("first instrument mass", firstMass, mission, 100.0, 90.0);
        checkLaws("clamped to 160 km minimum", clamped, mission.satellite().orbit(), 100.0, 200.0);

        // 4. Setters go through the canonical constructor, so validation still runs.
        try {
            altitude.set(mission, -5.0);
        } catch (IllegalArgumentException e) {
            System.out.println("rejected: " + e.getMessage());
        }

        // 5. A list index lens is partial.
        try {
            Mission.SATELLITE.andThen(Satellite.INSTRUMENTS).andThen(Lens.<Instrument>at(5)).get(mission);
        } catch (IndexOutOfBoundsException e) {
            System.out.println("partial lens: " + e.getMessage());
        }
    }
}
```

Output:

```text output
Mission[name=Sentinel, satellite=Satellite[id=S-1, orbit=Orbit[altitudeKm=750.0, inclinationDeg=98.2], instruments=[Instrument[name=radar, massKg=120.0], Instrument[name=camera, massKg=85.0]]]]
same as constructors: true, same as withers: true
original untouched: 700.0 km
siblings shared, not copied: true
SENTINEL at 750.0 km, first instrument 108.0 kg
composed altitude          get-set=true set-get=true set-set=true
first instrument mass      get-set=true set-get=true set-set=true
clamped to 160 km minimum  get-set=true set-get=false set-set=true
rejected: altitude must be positive, was -5.0
partial lens: Index: 5 Size: 2
```

## How it works

* **A lens is two functions.** `Lens<S, A>` stores a getter `S -> A` and a setter `(S, A) -> S`. Everything else is derived: `modify` is get, apply, set, and `over` turns that into a `UnaryOperator<S>`, so an update becomes a value you can put in a list, as the `plan` does. This is the same idea as [008](008-currying-composition.md): functions are data, and data composes.
* **`andThen` is the whole trick.** The composed getter just chains the two getters. The composed setter reads the intermediate part (`get(whole)`), replaces *its* part with the inner setter, and stores the changed intermediate back with the outer setter. Compose three lenses and the setter does exactly the nested rebuild from the problem section, once, generically, and never again by hand.
* **Only the path is rebuilt.** The `==` check in the output prints `true`: `raised` shares the very same `instruments` list as `mission`. A deep update allocates one new record per level on the path and reuses everything else. This is the same structural sharing that persistent data structures rely on.
* **The setter is a wither, so validation still runs.** `Orbit.withAltitudeKm` calls the canonical constructor, which is why setting `-5.0` through a three level lens is rejected with the constructor's own message. Lenses add no way around your invariants. The boilerplate you still write by hand is exactly one wither and one lens constant per component, which is the part JEP 468 (derived record creation, still only a candidate) would shrink. See [014](../02-patterns/014-record-withers.md).
* **The laws are a quality gate, not decoration.** A well behaved lens satisfies three rules, the same kind of rules as for [monads](001-maybe-monad.md):

| Law | In code | Meaning |
|---|---|---|
| Get-set | `set(s, get(s))` equals `s` | Writing back what you read changes nothing |
| Set-get | `get(set(s, a))` equals `a` | You read what you wrote |
| Set-set | `set(set(s, a), b)` equals `set(s, b)` | The second write wins completely |

  The composed lenses satisfy all three for the sample values. The `clamped` lens fails set-get: you write 100 km, it silently stores 160 km, and `get` returns 160. Nothing is wrong with a lens that normalizes, but it is no longer lawful, and any code that relies on the laws (generic helpers, round trip tests) can then be surprised.
* **`at(i)` is a partial lens.** A real lens must work for every whole. A list may be too short, so `at(5)` fails with an `IndexOutOfBoundsException`, and the last output line is its message. Optics libraries call the safe version an *affine traversal* or *optional* and return "no change" instead.

## Gotchas

* **You write the setters.** Java has no macros and no `with` expression yet, so each component needs a wither and a lens constant. For a handful of records that is fine. For hundreds, generate them: annotation processor based libraries such as Higher-Kinded-J (`@GenerateLenses`, for records and sealed types) or Derive4J (for Functional Java's optics) produce the constants for you.
* **Lenses focus on exactly one part.** "Every instrument in the list" needs a *traversal*, and "this branch of a sealed interface, if it is that branch" needs a *prism*. Those are the other optics, and they compose with lenses. This document stays with the lens.
* **Lists are copied whole.** `Lens.at(i)` copies the list on every set, which is O(n). For large collections, use a persistent collection library, or a lens on a `Map` entry only when maps are small.
* **Generic inference gets noisy.** Chained `andThen` calls with generic factories sometimes need a type witness (`Lens.<Instrument>at(5)` above). Use `var` for the composed lens and keep the type visible in the constant's name.
* **Boxing.** `Lens<Mission, Double>` boxes every number. Irrelevant for state updates, noticeable in a numeric inner loop.
* **Immutability is assumed.** A lens does not protect a mutable component. If a record holds an array or a mutable list, the "copy" shares it with the original.
* **Compose once, reuse.** Building `altitude` allocates a few lambdas. Keep composed lenses in `static final` fields rather than rebuilding them per call.

## When to use it (and when not to)

Lenses pay off when immutable state is **deeply nested and updated from many places**: UI or game state reducers, configuration trees, event sourced aggregates, AST rewriting. They also make "apply this list of updates in order" trivial, because each update is a function from state to state.

For one or two levels of nesting, a plain wither is shorter and everyone already reads it. Hand-rolling the infrastructure shown here is reasonable for a small domain model, a demo or a test fixture. For a large codebase, take an optics library, because the hard part is not `Lens` but the generated lenses, prisms and traversals around it. Whichever route you take, remember that the Java idiom for "change one field" is still a wither, and a lens is what you add when withers stop composing.

## Related

* [014 · Withers: Painless Copies of Immutable Records](../02-patterns/014-record-withers.md), the setter half of every lens
* [001 · The Maybe Monad from Scratch](001-maybe-monad.md), for laws that are checked with record equality
* [008 · Currying, Partial Application and Function Composition](008-currying-composition.md), for composition and functions as values
* [040 · Algebraic Data Types with Sealed Interfaces and Records](../05-modern-language/040-algebraic-data-types.md), the sum types that prisms focus on

## Sources

* Foster, Greenwald, Moore, Pierce and Schmitt, [Combinators for Bidirectional Tree Transformations](https://www.cis.upenn.edu/~bcpierce/papers/lenses-toplas-final.pdf) (ACM TOPLAS, 2007), the paper that introduced lenses and their laws
* Edward Kmett, [lens](https://hackage.haskell.org/package/lens), the Haskell library that made optics mainstream
* [Monocle](https://www.optics.dev/Monocle/), optics for Scala
* [Higher-Kinded-J](https://github.com/higher-kinded-j/higher-kinded-j), optics with generated lenses for Java records
* [JEP 468: Derived Record Creation (Preview)](https://openjdk.org/jeps/468), status Candidate
