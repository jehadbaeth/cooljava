# 029 · A Regex Engine in 30 Lines

> Rob Pike once wrote a regular expression matcher that fits on one page. It handles `c`, `.`, `^`, `$` and `*`, it is three small mutually recursive functions, and it is the best way to understand what `Pattern.compile` does for you (and why it sometimes does it for a very long time).

**Since:** Java 11 · **Category:** [Build It Yourself](../README.md#build-it-yourself) · **Level:** Intermediate · **Verdict:** 🧪 Party trick

## The problem

Regular expressions feel like magic: a notation, a compiler and a runtime hiding behind `Pattern.compile`. The JDK's `Pattern.java` is over 6,000 lines. Surely a regex engine is a serious piece of engineering?

It is. But the *core idea* is not. In 1998 Brian Kernighan and Rob Pike were writing *The Practice of Programming*, and its last chapter, "Notation", needed an example of a good notation paying off. The two wanted the smallest regular expression package that would illustrate the basic ideas while still recognizing a useful class of patterns. By Kernighan's account, Pike disappeared into his office and came back within an hour or two with about 30 lines of C. Kernighan later devoted a chapter of *Beautiful Code* (2007), "A Regular Expression Matcher", to explaining it.

This document is a Java port of that idea, plus an experiment the original does not need: what happens when a matcher like this meets the wrong input.

## The trick

The language has five constructs:

| Pattern | Matches |
|---|---|
| `c` | the literal character `c` |
| `.` | any single character |
| `^` | the start of the text (only at the start of the pattern) |
| `$` | the end of the text (only at the end of the pattern) |
| `c*` | zero or more copies of `c` (where `c` is a literal or `.`) |

Matching is a *search*: the pattern may match anywhere in the text unless it starts with `^`. Three functions answer three questions:

* **`match(re, text)`**: does the pattern occur anywhere in the text? It calls `matchHere` at every start position (or only at position 0 after a `^`).
* **`matchHere(re, r, text, t)`**: does the pattern from position `r` match the text starting exactly at position `t`? Each call peels off one pattern item: an empty pattern means success, `c*` hands over to `matchStar`, a final `$` succeeds only at the end of the text, and an ordinary character or `.` consumes one character from both and recurses.
* **`matchStar(c, re, r, text, t)`**: does `c*` followed by the rest of the pattern match here? It tries *zero* copies first. If the rest fails and the next character is `c` (or the star is `.`), it eats that character and tries again.

That is the entire engine. The "backtracking" everybody talks about is the loop in `matchStar`: when the rest of the pattern fails, control comes back to the loop, which gives up one more character to the star and retries.

The original is in C and walks pointers. The Java port passes a string and an index instead, which changes two lines in ways that matter (see Gotchas).

## Full example

The matcher is the first section: `match`, `matchHere` and `matchStar` come to 23 lines, plus one line of instrumentation (the original C is about 30). The rest is a second matcher of about 25 lines for contrast, a counting wrapper around `java.util.regex`, and the demo.

```java run
import java.util.*;
import java.util.regex.Pattern;

public class RegexDemo {

    static long calls;      // demo instrumentation: how many times matchHere ran

    // ---------- The matcher: c . ^ $ * ----------

    static boolean match(String re, String text) {
        if (re.startsWith("^")) return matchHere(re, 1, text, 0);
        for (int t = 0; t <= text.length(); t++) {          // <= : the end of the text is a start position too
            if (matchHere(re, 0, text, t)) return true;
        }
        return false;
    }

    static boolean matchHere(String re, int r, String text, int t) {
        calls++;
        if (r == re.length()) return true;
        if (r + 1 < re.length() && re.charAt(r + 1) == '*') return matchStar(re.charAt(r), re, r + 2, text, t);
        if (re.charAt(r) == '$' && r + 1 == re.length()) return t == text.length();
        if (t < text.length() && (re.charAt(r) == '.' || re.charAt(r) == text.charAt(t))) {
            return matchHere(re, r + 1, text, t + 1);
        }
        return false;
    }

    static boolean matchStar(char c, String re, int r, String text, int t) {
        while (true) {
            if (matchHere(re, r, text, t)) return true;     // zero more copies of c: try the rest of the pattern
            if (t >= text.length() || (text.charAt(t) != c && c != '.')) return false;
            t++;                                            // otherwise let the star eat one more character
        }
    }

    // ---------- Not Pike's: the same language, run Thompson style ----------
    // Instead of trying alternatives one after another, keep the SET of pattern positions
    // that are still alive and advance all of them together, one text character at a time.

    static long steps;      // demo instrumentation: (state, character) pairs processed

    static boolean matchNfa(String re, String text) {
        boolean anchored = re.startsWith("^");
        int first = anchored ? 1 : 0;
        Set<Integer> now = new HashSet<>();
        for (int t = 0; ; t++) {
            if (!anchored || t == 0) addState(re, first, now);      // an unanchored search may start anywhere
            for (int r : now) {
                if (r == re.length() || (isEndAnchor(re, r) && t == text.length())) return true;
            }
            if (t == text.length()) return false;
            Set<Integer> next = new HashSet<>();
            for (int r : now) {
                steps++;
                if (r == re.length() || isEndAnchor(re, r)) continue;
                if (re.charAt(r) != '.' && re.charAt(r) != text.charAt(t)) continue;
                addState(re, starred(re, r) ? r : r + 1, next);
            }
            now = next;
        }
    }

    static boolean starred(String re, int r) { return r + 1 < re.length() && re.charAt(r + 1) == '*'; }
    static boolean isEndAnchor(String re, int r) { return r == re.length() - 1 && re.charAt(r) == '$'; }

    // A state is a position in the pattern. A starred item may also be skipped, so its successor is alive too.
    static void addState(String re, int r, Set<Integer> states) {
        if (states.add(r) && starred(re, r)) addState(re, r + 2, states);
    }

    // ---------- Demo ----------

    /** Counts how often java.util.regex reads a character. Deterministic on a given JDK, unlike a stopwatch. */
    static final class CountingText implements CharSequence {
        final String text;
        long reads;
        CountingText(String text) { this.text = text; }
        public int length() { return text.length(); }
        public char charAt(int index) { reads++; return text.charAt(index); }
        public CharSequence subSequence(int start, int end) { return text.subSequence(start, end); }
        @Override public String toString() { return text; }
    }

    static long reads(String regex, int n) {
        var counting = new CountingText("a".repeat(n) + "!");
        Pattern.compile(regex).matcher(counting).find();
        return counting.reads;
    }

    static String randomPattern(Random random) {
        var sb = new StringBuilder();
        if (random.nextInt(4) == 0) sb.append('^');
        for (int items = 1 + random.nextInt(4); items > 0; items--) {
            sb.append("ab.".charAt(random.nextInt(3)));
            if (random.nextInt(5) < 2) sb.append('*');
        }
        if (random.nextInt(4) == 0) sb.append('$');
        return sb.toString();
    }

    static String randomText(Random random) {
        var sb = new StringBuilder();
        for (int length = random.nextInt(9); length > 0; length--) sb.append("ab".charAt(random.nextInt(2)));
        return sb.toString();
    }

    public static void main(String[] args) {
        String[][] cases = {
            {"abc", "xxabcxx"}, {"^abc", "abcd"}, {"^abc", "xabc"}, {"abc$", "xabc"}, {"abc$", "abcx"},
            {"a.c", "xabcx"}, {"ab*c", "ac"}, {"ab*c", "abbbc"}, {"ab*c", "abbbd"}, {"^.*b$", "aaab"},
            {"x*", ""}, {"$", ""}, {"^$", ""}, {"^$", "a"}
        };
        for (String[] c : cases) {
            boolean expected = Pattern.compile(c[0]).matcher(c[1]).find();
            System.out.printf("%-7s on %-9s -> %-5b (java.util.regex says %b)%n", c[0], '"' + c[1] + '"', match(c[0], c[1]), expected);
        }

        // 5000 random patterns and texts: the toy, the NFA and java.util.regex must always agree.
        var random = new Random(7);
        int matches = 0, disagreements = 0;
        for (int i = 0; i < 5000; i++) {
            String re = randomPattern(random), text = randomText(random);
            boolean expected = Pattern.compile(re).matcher(text).find();
            if (expected) matches++;
            if (match(re, text) != expected || matchNfa(re, text) != expected) disagreements++;
        }
        System.out.println("random cases: 5000, matching: " + matches + ", disagreements: " + disagreements);

        System.out.println("--- a*a*a*a*b against n times 'a' (no b, so every way to split the a's is tried)");
        System.out.println("   n   backtracking calls   NFA steps");
        for (int n : new int[] {10, 20, 40, 80}) {
            String text = "a".repeat(n);
            calls = 0;
            steps = 0;
            match("a*a*a*a*b", text);
            matchNfa("a*a*a*a*b", text);
            System.out.printf("%4d %20d %11d%n", n, calls, steps);
        }

        System.out.println("--- java.util.regex, characters read on n times 'a' followed by '!'");
        System.out.println("   n    (a|aa)+$   (a|aa)+\\1$");
        for (int n = 10; n <= 26; n += 4) {
            System.out.printf("%4d %11d %12d%n", n, reads("(a|aa)+$", n), reads("(a|aa)+\\1$", n));
        }
    }
}
```

Output:

```text output
abc     on "xxabcxx" -> true  (java.util.regex says true)
^abc    on "abcd"    -> true  (java.util.regex says true)
^abc    on "xabc"    -> false (java.util.regex says false)
abc$    on "xabc"    -> true  (java.util.regex says true)
abc$    on "abcx"    -> false (java.util.regex says false)
a.c     on "xabcx"   -> true  (java.util.regex says true)
ab*c    on "ac"      -> true  (java.util.regex says true)
ab*c    on "abbbc"   -> true  (java.util.regex says true)
ab*c    on "abbbd"   -> false (java.util.regex says false)
^.*b$   on "aaab"    -> true  (java.util.regex says true)
x*      on ""        -> true  (java.util.regex says true)
$       on ""        -> true  (java.util.regex says true)
^$      on ""        -> true  (java.util.regex says true)
^$      on "a"       -> false (java.util.regex says false)
random cases: 5000, matching: 3150, disagreements: 0
--- a*a*a*a*b against n times 'a' (no b, so every way to split the a's is tried)
   n   backtracking calls   NFA steps
  10                 4367          50
  20                65779         100
  40              1370753         200
  80             34826301         400
--- java.util.regex, characters read on n times 'a' followed by '!'
   n    (a|aa)+$   (a|aa)+\1$
  10          69         3011
  14          93        21275
  18         117       146669
  22         141      1006343
  26         165      6898847
```

## How it works

* **A walk through `ab*c` on `"abbc"`.** `match` calls `matchHere` at position 0. The first item `a` matches and consumes one character. The next item is `b*`, so control passes to `matchStar`, which first tries the rest of the pattern (`c`) against `b` and fails. The star eats a `b` and tries `c` against the second `b`: fails again. It eats the second `b`, and `c` now meets `c`: success. If the text had been `"abbd"`, the star would run out of `b`s, return `false`, and `match` would move on to start position 1.
* **The table is the specification.** The rows with empty text are the interesting ones. `x*` and `$` match `""` only because the loop in `match` uses `<=`: with `t < text.length()` the loop body would never run on empty text and both rows would print `false`. (`^$` skips the loop, because the `^` branch calls `matchHere` once.)
* **The agreement check is a property test.** 5000 random patterns (an optional `^`, one to four items from `a`, `b` and `.`, each possibly starred, an optional `$`) meet random texts over `a` and `b`. 3150 of them match, and the toy, the NFA matcher and `java.util.regex` never disagree. This is the same idea as [026](026-property-based-testing.md) with `java.util.regex` as the oracle.
* **Reading the blowup table.** The pattern `a*a*a*a*b` can never match `aaaa...` because there is no `b`, so the matcher must try *every* way to split the `a`s between the four stars, from every start position. Doubling `n` multiplies the calls by about 15, 21 and 25, on the way to 32: the work grows like n to the fifth power. That is only polynomial, but a power of five turns 80 characters into 34 million calls. Each extra star adds one to the exponent.
* **The Thompson matcher does not care.** The same 400 steps (5 states times 80 characters, exactly 5n) answer the same question. Ken Thompson's 1968 algorithm turns the pattern into a nondeterministic automaton and advances *all* its live states together, one text character at a time. Nothing is ever retried, so the work is bounded by pattern length times text length. For this tiny language the pattern positions are the automaton states, so `matchNfa` needs no compile step.
* **Real engines blow up exponentially.** With nested quantifiers or alternation inside a loop, a backtracking engine multiplies choices instead of adding them. Russ Cox's article shows Perl needing over 10^15 years for a 100 character input on the pattern `a?` repeated n times followed by `a` repeated n times, where a Thompson matcher needs under 200 microseconds. The last table shows the JDK's version of this. `(a|aa)+$` is linear (24 more reads per four more characters), because `Pattern` memoizes failed loop positions: a comment in `Pattern.java` says it optimizes the greedy `Loop` "to prevent exponential backtracking, IF there is no group ref in this pattern". Add a back reference, `(a|aa)+\1$`, and the optimization switches off. Reads now grow by a factor of about 6.9 for every four extra characters, which is the golden ratio to the fourth power: the number of ways to split a run of `a`s into pieces of one and two characters is a Fibonacci number. The exact counts belong to the JDK's implementation, though JDK 17, 24 and 25 print identical numbers here. The shape is the point.
* **Why back references matter.** Cox points out that nobody knows how to match patterns with back references efficiently (the problem is NP-complete). That is the price Perl, PCRE, Python, Ruby and Java pay for the feature, and the reason RE2 and Go's `regexp` leave it out and can promise linear time.

## Gotchas

* **The port has two traps that C hides.** C strings end with a NUL byte, so `regexp[1]` is always safe to read and `do { } while (*text++ != '\0')` naturally tries the empty string at the end. In Java you need the `r + 1 < re.length()` guard and the `<=` loop bound. Forget either and you get a `StringIndexOutOfBoundsException` or wrong answers on empty text.
* **The language is tiny on purpose.** `*` applies to one character or `.`, never a group. There is no `+`, `?`, `|`, `{n,m}`, character class, escape, group or capture, so there is no way to match a literal `*` or `.`.
* **It answers yes or no, and prefers the shortest match.** `matchStar` tries zero copies first, so a version that returned *where* the match ends would report the shortest one. `grep` does not care, but a `sed`-style substitution needs the longest and would have to loop the other way.
* **Characters are UTF-16 code units.** `.` matches half of a surrogate pair, so an emoji counts as two characters.
* **`calls` and `steps` are static counters** for the demo, which makes the matchers not thread-safe as written. Delete the instrumentation lines in real use.

## When to use it (and when not to)

Build it to understand what a regex engine does, to explain backtracking to a colleague, or as a starting point for a different tiny matcher (shell globs are the same recursion with `?` and `*` meaning different things). Do not ship it.

For real work use `java.util.regex`, and keep an eye on every pattern that has nested quantifiers, alternations inside loops or back references, especially when the pattern or the text comes from outside. Possessive quantifiers and atomic groups tame backtracking, see [097](../11-jdk-gems/097-regex-power-tools.md). If you must run untrusted patterns or inputs, use [RE2/J](https://github.com/google/re2j), a Java port of RE2 with a linear time guarantee and no back references. The toy leaves out groups and captures, alternation, `+`, `?` and counted repeats, classes and escapes, flags and case folding, Unicode, match positions, finding all matches, and the compiled, optimized node graph that `Pattern` builds once and reuses.

## Related

* [097 · Regex Power Tools](../11-jdk-gems/097-regex-power-tools.md), for named groups, possessive quantifiers and atomic groups
* [026 · Property-Based Testing in 80 Lines](026-property-based-testing.md), the random agreement check above is exactly this
* [028 · Parser Combinators: Grammars as Code](028-parser-combinators.md), another small notation turned into a program

## Sources

* Brian Kernighan, [A Regular Expression Matcher](https://www.cs.princeton.edu/courses/archive/spr09/cos333/beautiful.html), chapter 1 of *Beautiful Code* (Oram and Wilson, eds., O'Reilly, 2007), which tells the story of Rob Pike's 30 lines and explains them
* Brian Kernighan and Rob Pike, [The Practice of Programming](https://www.cs.princeton.edu/~bwk/tpop.webpage/) (Addison-Wesley, 1999), where the matcher first appeared, in chapter 9
* Russ Cox, [Regular Expression Matching Can Be Simple And Fast](https://swtch.com/~rsc/regexp/regexp1.html) (2007), on backtracking versus Ken Thompson's 1968 automaton simulation
* [`java.util.regex.Pattern` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/regex/Pattern.html)
* [RE2/J](https://github.com/google/re2j), a linear time regular expression engine for Java
