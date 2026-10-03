# 096 · java.time Tricks: Clocks, Adjusters and Time Zones

> `LocalDate.now()` is a hidden global variable, and a great many date bugs live in it. Hand your code a `Clock`, learn three adjusters, and the rest of `java.time` stops biting.

**Since:** Java 16 · **Category:** [JDK Gems](../README.md#jdk-gems) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

Date code fails in four predictable ways:

* It calls `Instant.now()` or `LocalDate.now()` deep inside a method, so a test can only run it "now". The test passes today and fails at midnight, on the 31st, or in another time zone.
* It counts "a day" as 86,400 seconds, and twice a year a day is 23 or 25 hours long.
* It builds a `LocalDateTime` that does not exist (the hour skipped by spring forward) or exists twice (the hour repeated in autumn), and the library silently picks something.
* It formats with `YYYY` instead of `yyyy`, which works for most of the year, in some countries.

`java.time` (Java 8, specified in JSR 310 under the leadership of Stephen Colebourne, Roger Riggs and Michael Nascimento Santos) has an answer for each one. Most of them are small enough to miss.

## The trick

**Inject a `Clock`.** Every `now()` method in `java.time` has an overload that takes a `Clock`. In production you pass `Clock.systemUTC()` once at the edge of the program. In a test you pass `Clock.fixed(instant, zone)`, and the code under test cannot tell the difference. `Clock.offset(clock, duration)` shifts a clock for time travel, and `Clock.tick(clock, duration)` rounds one down to a boundary.

**Pick the type that matches the question:**

| Question | Type |
|---|---|
| Which exact moment on the timeline? | `Instant` |
| What does the wall clock say in this place? | `ZonedDateTime` |
| Which calendar date, no zone? | `LocalDate` |
| How much exact time passed (seconds)? | `Duration` |
| How far apart on the calendar (years, months, days)? | `Period` |

**Move dates with adjusters.** `TemporalAdjusters` holds the common ones (`lastInMonth`, `dayOfWeekInMonth`, `next`, `firstDayOfNextMonth`), and `TemporalAdjuster` is a one-method interface, so your own rule is a lambda. It works on every temporal type and keeps the type you started with.

## Full example

The program uses only fixed instants, fixed zones and fixed locales, so every line is deterministic. DST rules come from the JDK's bundled time zone database (the 2026 changes for Europe/Berlin follow the stable EU rule).

```java run
import java.time.*;
import java.time.format.*;
import java.time.temporal.*;
import java.time.zone.ZoneRules;
import java.util.*;

public class TimeTricks {

    /** Logic that asks an injected Clock for the time, never the system. */
    record Trial(Clock clock, Instant started, Duration length) {
        Duration remaining() { return Duration.between(clock.instant(), started.plus(length)); }
        boolean isActive() { return clock.instant().isBefore(started.plus(length)); }
    }

    /** The next day that is neither a weekend nor a holiday. Keeps the type (and the time of day). */
    static TemporalAdjuster nextWorkingDay(Set<LocalDate> holidays) {
        return temporal -> {
            LocalDate day = LocalDate.from(temporal);
            do {
                day = day.plusDays(1);
            } while (day.getDayOfWeek().getValue() >= 6 || holidays.contains(day));
            return temporal.with(day);
        };
    }

    static void show(String label, Object value) {
        System.out.printf("%-36s %s%n", label, value);
    }

    public static void main(String[] args) {
        ZoneId berlin = ZoneId.of("Europe/Berlin");

        System.out.println("== Clocks");
        Instant start = Instant.parse("2026-10-03T08:00:00Z");
        Clock day10 = Clock.fixed(start.plus(Duration.ofDays(10)), ZoneOffset.UTC);
        Trial trial = new Trial(day10, start, Duration.ofDays(14));
        show("remaining on day 10", trial.remaining());
        show("active on day 10", trial.isActive());
        show("active on day 15 (offset clock)", new Trial(Clock.offset(day10, Duration.ofDays(5)), start, Duration.ofDays(14)).isActive());
        show("a fixed clock never advances", day10.instant().equals(day10.instant()));
        Instant precise = Instant.parse("2026-10-03T10:07:42.123456789Z");
        show("tick(15 minutes)", Clock.tick(Clock.fixed(precise, ZoneOffset.UTC), Duration.ofMinutes(15)).instant());
        Instant evening = Instant.parse("2026-10-03T20:00:00Z");
        show("today in UTC", LocalDate.now(Clock.fixed(evening, ZoneOffset.UTC)));
        show("today in Tokyo", LocalDate.now(Clock.fixed(evening, ZoneId.of("Asia/Tokyo"))));

        System.out.println("== Instant truncation");
        show("truncatedTo(MILLIS)", precise.truncatedTo(ChronoUnit.MILLIS));
        show("truncatedTo(HOURS)", precise.truncatedTo(ChronoUnit.HOURS));
        show("truncatedTo(DAYS)", precise.truncatedTo(ChronoUnit.DAYS));
        try {
            precise.truncatedTo(ChronoUnit.WEEKS);
        } catch (RuntimeException e) {
            show("truncatedTo(WEEKS)", e.getMessage());
        }

        System.out.println("== Adjusters");
        LocalDate saturday = LocalDate.of(2026, 10, 3);
        show("day of week", saturday.getDayOfWeek());
        show("last Friday of the month", saturday.with(TemporalAdjusters.lastInMonth(DayOfWeek.FRIDAY)));
        show("second Tuesday of the month", saturday.with(TemporalAdjusters.dayOfWeekInMonth(2, DayOfWeek.TUESDAY)));
        show("next Monday", saturday.with(TemporalAdjusters.next(DayOfWeek.MONDAY)));
        show("first day of next month", saturday.with(TemporalAdjusters.firstDayOfNextMonth()));
        Set<LocalDate> holidays = Set.of(LocalDate.of(2026, 12, 25), LocalDate.of(2026, 12, 26));
        TemporalAdjuster workingDay = nextWorkingDay(holidays);
        show("next working day after 2026-12-24", LocalDate.of(2026, 12, 24).with(workingDay));
        show("same adjuster on a ZonedDateTime", ZonedDateTime.of(2026, 12, 24, 16, 30, 0, 0, berlin).with(workingDay));

        System.out.println("== Duration vs Period");
        ZonedDateTime saturdayNoon = ZonedDateTime.of(2026, 3, 28, 12, 0, 0, 0, berlin);
        show("+ Duration.ofDays(1) over DST", saturdayNoon.plus(Duration.ofDays(1)));
        show("+ Period.ofDays(1) over DST", saturdayNoon.plus(Period.ofDays(1)));
        LocalDate jan31 = LocalDate.of(2026, 1, 31);
        show("Jan 31 plus one month", jan31.plusMonths(1));
        Period gap = Period.between(jan31, LocalDate.of(2026, 3, 1));
        show("Period.between Jan 31, Mar 1", gap + " (days part: " + gap.getDays() + ")");
        show("ChronoUnit.DAYS.between", ChronoUnit.DAYS.between(jan31, LocalDate.of(2026, 3, 1)));
        Duration twentyFive = Duration.ofHours(25);
        show("Duration.ofHours(25)", twentyFive + " = " + twentyFive.toDaysPart() + " day + " + twentyFive.toHoursPart() + " hour");

        System.out.println("== DST gap and overlap in Europe/Berlin");
        ZoneRules rules = berlin.getRules();
        LocalDateTime inGap = LocalDateTime.of(2026, 3, 29, 2, 30);
        show("valid offsets for 02:30 on 03-29", rules.getValidOffsets(inGap));
        show("transition", rules.getTransition(inGap));
        show("ZonedDateTime.of(02:30)", ZonedDateTime.of(inGap, berlin));
        LocalDateTime inOverlap = LocalDateTime.of(2026, 10, 25, 2, 30);
        show("valid offsets for 02:30 on 10-25", rules.getValidOffsets(inOverlap));
        ZonedDateTime earlier = ZonedDateTime.of(inOverlap, berlin);
        ZonedDateTime later = earlier.withLaterOffsetAtOverlap();
        show("overlap, default (earlier)", earlier);
        show("overlap, withLaterOffsetAtOverlap", later);
        show("time between those two", Duration.between(earlier, later));
        show("length of 2026-03-29", Duration.between(
                LocalDate.of(2026, 3, 29).atStartOfDay(berlin), LocalDate.of(2026, 3, 30).atStartOfDay(berlin)));
        show("length of 2026-10-25", Duration.between(
                LocalDate.of(2026, 10, 25).atStartOfDay(berlin), LocalDate.of(2026, 10, 26).atStartOfDay(berlin)));
        show("midnight can be missing (Sao Paulo)", LocalDate.of(2018, 11, 4).atStartOfDay(ZoneId.of("America/Sao_Paulo")));

        System.out.println("== YearMonth and MonthDay");
        YearMonth card = YearMonth.parse("10/27", DateTimeFormatter.ofPattern("MM/yy"));
        show("card expiry 10/27", card + " valid through " + card.atEndOfMonth());
        show("days in 2028-02", YearMonth.of(2028, 2).lengthOfMonth());
        MonthDay leapDay = MonthDay.of(Month.FEBRUARY, 29);
        show("Feb 29 in 2027", leapDay.atYear(2027));
        show("Feb 29 valid in 2028", leapDay.isValidYear(2028));

        System.out.println("== Formatter pitfalls");
        for (LocalDate date : List.of(LocalDate.of(2025, 12, 29), LocalDate.of(2021, 1, 1))) {
            for (Locale locale : List.of(Locale.US, Locale.GERMANY)) {
                show(date + " " + locale, "yyyy=" + date.format(DateTimeFormatter.ofPattern("yyyy", locale))
                        + " YYYY=" + date.format(DateTimeFormatter.ofPattern("YYYY", locale)));
            }
        }
        LocalTime afternoon = LocalTime.of(15, 0);
        show("15:00 as hh:mm / HH:mm", afternoon.format(DateTimeFormatter.ofPattern("hh:mm"))
                + " / " + afternoon.format(DateTimeFormatter.ofPattern("HH:mm")));
        DateTimeFormatter smart = DateTimeFormatter.ofPattern("uuuu-MM-dd");
        show("SMART parses 2026-02-30 as", LocalDate.parse("2026-02-30", smart));
        try {
            LocalDate.parse("2026-02-30", smart.withResolverStyle(ResolverStyle.STRICT));
        } catch (DateTimeParseException e) {
            show("STRICT says", e.getMessage());
        }
        try {
            LocalDate.parse("2026-10-03", DateTimeFormatter.ofPattern("yyyy-MM-dd").withResolverStyle(ResolverStyle.STRICT));
        } catch (DateTimeParseException e) {
            show("STRICT with yyyy (no era)", "fails");
        }
    }
}
```

Output:

```text output
== Clocks
remaining on day 10                  PT96H
active on day 10                     true
active on day 15 (offset clock)      false
a fixed clock never advances         true
tick(15 minutes)                     2026-10-03T10:00:00Z
today in UTC                         2026-10-03
today in Tokyo                       2026-10-04
== Instant truncation
truncatedTo(MILLIS)                  2026-10-03T10:07:42.123Z
truncatedTo(HOURS)                   2026-10-03T10:00:00Z
truncatedTo(DAYS)                    2026-10-03T00:00:00Z
truncatedTo(WEEKS)                   Unit is too large to be used for truncation
== Adjusters
day of week                          SATURDAY
last Friday of the month             2026-10-30
second Tuesday of the month          2026-10-13
next Monday                          2026-10-05
first day of next month              2026-11-01
next working day after 2026-12-24    2026-12-28
same adjuster on a ZonedDateTime     2026-12-28T16:30+01:00[Europe/Berlin]
== Duration vs Period
+ Duration.ofDays(1) over DST        2026-03-29T13:00+02:00[Europe/Berlin]
+ Period.ofDays(1) over DST          2026-03-29T12:00+02:00[Europe/Berlin]
Jan 31 plus one month                2026-02-28
Period.between Jan 31, Mar 1         P1M1D (days part: 1)
ChronoUnit.DAYS.between              29
Duration.ofHours(25)                 PT25H = 1 day + 1 hour
== DST gap and overlap in Europe/Berlin
valid offsets for 02:30 on 03-29     []
transition                           Transition[Gap at 2026-03-29T02:00+01:00 to +02:00]
ZonedDateTime.of(02:30)              2026-03-29T03:30+02:00[Europe/Berlin]
valid offsets for 02:30 on 10-25     [+02:00, +01:00]
overlap, default (earlier)           2026-10-25T02:30+02:00[Europe/Berlin]
overlap, withLaterOffsetAtOverlap    2026-10-25T02:30+01:00[Europe/Berlin]
time between those two               PT1H
length of 2026-03-29                 PT23H
length of 2026-10-25                 PT25H
midnight can be missing (Sao Paulo)  2018-11-04T01:00-02:00[America/Sao_Paulo]
== YearMonth and MonthDay
card expiry 10/27                    2027-10 valid through 2027-10-31
days in 2028-02                      29
Feb 29 in 2027                       2027-02-28
Feb 29 valid in 2028                 true
== Formatter pitfalls
2025-12-29 en_US                     yyyy=2025 YYYY=2026
2025-12-29 de_DE                     yyyy=2025 YYYY=2026
2021-01-01 en_US                     yyyy=2021 YYYY=2021
2021-01-01 de_DE                     yyyy=2021 YYYY=2020
15:00 as hh:mm / HH:mm               03:00 / 15:00
SMART parses 2026-02-30 as           2026-02-28
STRICT says                          Text '2026-02-30' could not be parsed: Invalid date 'FEBRUARY 30'
STRICT with yyyy (no era)            fails
```

## How it works

**Clocks.** `Clock` is an abstract class with two real methods, `instant()` and `getZone()`, and every `now()` in `java.time` reads from it. The trial ends after 14 days, the fixed clock stands on day 10, so `remaining()` is `PT96H`. `Clock.offset(day10, Duration.ofDays(5))` is a clock on day 15, and the trial is over. A fixed clock never advances (that line of the output is `true`), which is what you want in an assertion. If a test needs time to pass, write a ten-line `Clock` subclass with a mutable instant: the class is meant to be extended.

The zone belongs to the clock too. The same instant, `2026-10-03T20:00:00Z`, is October 3 in UTC and already October 4 in Tokyo, so `LocalDate.now(clock)` gives different answers. This is the classic "the nightly job ran for the wrong day" bug, and it is why `LocalDate.now()` without an argument (which uses the JVM default zone) deserves suspicion. `Clock.tick(clock, Duration.ofMinutes(15))` rounds the reading down to a 15 minute boundary: `10:07:42.123456789` becomes `10:00:00`.

**Truncation.** `Instant.truncatedTo(unit)` accepts units up to `DAYS` (a UTC day for an `Instant`). Asking for `WEEKS` throws, as the output shows. Use it before comparing an instant to one that went through a database column or a JSON field, because those usually keep milliseconds or microseconds and `Instant.now()` can carry more digits than that, depending on the JDK and the operating system.

**Adjusters.** The date `2026-10-03` is a Saturday. `lastInMonth(FRIDAY)` gives October 30, `dayOfWeekInMonth(2, TUESDAY)` gives the second Tuesday (October 13, the shape of "patch Tuesday"), `next(MONDAY)` skips ahead, and `firstDayOfNextMonth()` is a rollover helper. The custom `nextWorkingDay` is only a lambda from a temporal to a temporal. It starts from December 24 (a Thursday), skips the two holidays and the weekend, and lands on Monday the 28th. Returning `temporal.with(day)` instead of the bare `LocalDate` is the important detail: the same adjuster applied to a `ZonedDateTime` keeps the 16:30 and the zone, and still re-resolves the offset for the new date.

**Duration or Period.** A `Duration` is an exact amount of seconds, so `Duration.ofDays(1)` is always 24 hours. A `Period` is calendar arithmetic: years, months and days, applied to the local date and time. Across the spring DST change in Berlin, one day as 24 hours moves noon to `13:00` (the clock skipped an hour), and one day as a `Period` keeps `12:00`. Ask yourself which one the business means. "The trial lasts 14 days" is a `Period`. "The cache entry lives 86,400 seconds" is a `Duration`.

`Period` has its own surprises. January 31 plus one month is February 28, clamped to the last valid day without an exception. `Period.between(Jan 31, Mar 1)` is `P1M1D`, and `getDays()` returns the *1*, not the 29 that `ChronoUnit.DAYS.between` gives you. `Duration` has no months at all, and Java 9's `toDaysPart()` and `toHoursPart()` split `PT25H` into a day and an hour for display.

**DST, gap and overlap.** In Europe/Berlin the clocks jump from 02:00 to 03:00 on 2026-03-29, so `02:30` does not exist. `ZoneRules.getValidOffsets` returns an empty list, `getTransition` describes the gap, and `ZonedDateTime.of` quietly moves the time forward by the length of the gap to `03:30+02:00`. On 2026-10-25 the clocks go back from 03:00 to 02:00, so `02:30` happens twice, and `getValidOffsets` returns both `+02:00` and `+01:00`. `ZonedDateTime.of` picks the earlier one, and `withLaterOffsetAtOverlap()` picks the other. They are exactly one hour apart on the timeline. The two dates also have a different length: a day is `PT23H` in March and `PT25H` in October. `atStartOfDay(zone)` exists because midnight itself can be missing. São Paulo started its 2018 summer time at midnight, so November 4, 2018 began at `01:00-02:00`.

**YearMonth and MonthDay.** They are the types for the questions a `LocalDate` answers badly. A card that expires `10/27` is a `YearMonth` (parsed here with `MM/yy`) and is valid through `atEndOfMonth()`. A birthday is a `MonthDay`: February 29 in 2027 is adjusted to February 28 by `atYear`, and `isValidYear` tells you whether the day exists at all.

**Formatter pitfalls.** `YYYY` is the *week-based* year, not the calendar year. For the last days of December and the first days of January it can belong to the neighbouring year, and which way depends on the locale's week definition. The US counts weeks from Sunday and calls the week containing January 1 week 1. ISO (Germany) starts on Monday and needs at least four days in the new year. So `2025-12-29` prints `2026` in both (it sits in week 1 of 2026), while `2021-01-01` prints `2021` in the US and `2020` in Germany (week 53 of 2020). The bug hides for most of the year and in most test locales. `hh` is the 12-hour clock, so 15:00 prints as `03:00` with no AM/PM marker. Finally, `uuuu` with the default SMART resolver turns `2026-02-30` into February 28, a `STRICT` formatter rejects it, and `yyyy` (year of era) cannot be used with `STRICT` at all unless the pattern also has an era letter. Use `uuuu` and `STRICT` when you validate input.

## Gotchas

* **A fixed clock is only as good as its zone.** `Clock.fixed(instant, ZoneId.systemDefault())` makes a test that passes in the CI container (UTC) and fails on a laptop. Give fixed clocks an explicit zone.
* **Do not store a future local appointment as an `Instant`.** "Meeting at 09:00 in Berlin on 2027-03-30" is a `LocalDateTime` plus a `ZoneId`. If a government changes its DST rule before then, the instant for 09:00 moves, and a stored `Instant` silently ends up an hour off. For events that already happened, store the `Instant`.
* **`ZonedDateTime.equals` compares the zone too.** The same instant in Berlin and in UTC is not `equals`, but `isEqual` (which compares only the instant) says `true`. Keep zoned values out of `HashSet`s and use `Instant` as the key.
* **`ZonedDateTime.ofStrict` throws in a gap.** `of` and `ofLocal` repair gaps and overlaps silently. If a user-supplied time in a gap should be an error, validate with `ZoneRules.getValidOffsets` or use `ofStrict`, which throws a `DateTimeException`.
* **`Duration.between` needs a time-based argument.** `Duration.between(LocalDate, LocalDate)` throws `UnsupportedTemporalTypeException: Unsupported unit: Seconds`. For dates use `Period.between` or `ChronoUnit.DAYS.between`.
* **Time zone data ages.** The output above comes from the time zone database inside this JDK. Rules change a few times a year somewhere in the world, so keep the JDK patched: each update ships the current data.

## When to use it (and when not to)

Use an injected `Clock` in any class whose behavior depends on "now": expiry, rate limits, retries, schedulers, audit stamps. It costs one constructor parameter, and every time test becomes a plain unit test with no sleeping. Pass `Clock.systemUTC()` at the application edge, and a fixed clock in the tests.

Use adjusters for business calendars ("last Friday", "next working day"). If the rules are really a calendar (public holidays by country, banking days), do not grow the lambda: keep the holiday data in a proper calendar component and let the adjuster call it.

Skip the `Clock` parameter for throwaway scripts and for code that only logs a timestamp. Keep `java.util.Date` and `Calendar` at the borders of legacy APIs, and nowhere else.


## Related

* [022 · Retry with Exponential Backoff and Jitter](../03-build-it-yourself/022-retry-backoff.md), where an injectable clock and sleeper keep tests deterministic
* [023 · A Circuit Breaker in 80 Lines](../03-build-it-yourself/023-circuit-breaker.md), whose open timeout is a `Clock` question
* [024 · Token Bucket Rate Limiter](../03-build-it-yourself/024-token-bucket.md), which also needs a fake time source

## Sources

* [`java.time.Clock` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/time/Clock.html)
* [`TemporalAdjusters` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/time/temporal/TemporalAdjusters.html)
* [`ZonedDateTime` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/time/ZonedDateTime.html), on gaps and overlaps
* [`DateTimeFormatter` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/time/format/DateTimeFormatter.html), the pattern letter table
* [The Java Tutorials: Date Time](https://docs.oracle.com/javase/tutorial/datetime/)
