# 097 · Regex Power Tools

> `java.util.regex` has been in the JDK since 1.4, and most code still uses a small corner of it. Named groups, lambda replacements, match streams, lookarounds and possessive quantifiers turn it from a source of incidents into a small parser toolkit.

**Since:** Java 20 · **Category:** [JDK Gems](../README.md#jdk-gems) · **Level:** Intermediate · **Verdict:** ⚠️ Situational

## The problem

Regex code tends to be written once and feared forever: numbered groups (`group(3)`, was it 3?), `while (m.find())` loops with a `StringBuilder`, one giant pattern nobody dares to touch, and the occasional production incident where a single request pins a CPU at 100 percent because of a pattern that looked fine.

The JDK has had better answers for years. Most of them are small.

## The trick

| Tool | What it gives you | Since |
|---|---|---|
| `(?<name>...)`, `group("name")`, `\k<name>`, `${name}` | readable groups, reusable in backreferences and replacements | 7 |
| `Matcher.replaceAll(Function<MatchResult,String>)` | compute each replacement in Java | 9 |
| `Matcher.results()` | a lazy `Stream<MatchResult>` of all matches | 9 |
| `MatchResult.group(String)` and `namedGroups()` | named access on a match result | 20 |
| `Pattern.asPredicate()` / `asMatchPredicate()` | a pattern as a `Predicate<String>`, "contains" or "is entirely" | 8 / 11 |
| `Pattern.splitAsStream(...)` | a lazy split | 8 |
| `(?=...)`, `(?!...)`, `(?<=...)`, `(?<!...)` | zero-width conditions before or after the current position | 1.4 |
| `\R` | any linebreak, including `\r\n` as one unit | 8 |
| `*+`, `++`, `?+` and `(?>...)` | possessive quantifiers and atomic groups: no backtracking into them | 1.4 |
| `(?i)`, `(?x)`, `(?s)`, `(?m)`, `(?i:...)` | flags inside the pattern, and `(?x)` allows comments | 1.4 |

Almost everything is older than the badge above. The example uses `MatchResult.group(String)` inside lambdas (Java 20); before that, use group numbers there. The rest of the example needs Java 16 (`Stream.toList()`, plus text blocks from 15), and the regex features themselves go back much further.

## Full example

```java run
import java.util.*;
import java.util.regex.*;
import java.util.stream.*;

public class RegexTools {

    public static void main(String[] args) {
        // 1. Named groups: read by name, reuse in the replacement string, reuse in a backreference.
        Pattern logLine = Pattern.compile("(?<date>\\d{4}-\\d{2}-\\d{2}) (?<level>[A-Z]+) (?<user>\\w+): (?<msg>.*)");
        Matcher line = logLine.matcher("2026-10-03 WARN mo: disk at 91%");
        if (line.matches()) {
            System.out.println(line.group("level") + " from " + line.group("user") + " on " + line.group("date"));
        }
        System.out.println(Pattern.compile("(?<y>\\d{4})-(?<m>\\d{2})-(?<d>\\d{2})")
                .matcher("released 2026-10-03").replaceAll("${d}.${m}.${y}"));
        Matcher quoted = Pattern.compile("(?<q>['\"])(?<body>.*?)\\k<q>").matcher("say \"it's fine\" or 'no'");
        while (quoted.find()) System.out.println("quoted: " + quoted.group("body"));

        // 2. replaceAll(Function): compute each replacement. Careful, the result is still a template.
        Map<String, String> env = Map.of("USER", "mo", "HOME", "C:\\Users\\mo");
        Pattern placeholder = Pattern.compile("\\$\\{(\\w+)}");
        String template = "hi ${USER}, home is ${HOME}, shell is ${SHELL}";
        System.out.println(placeholder.matcher(template).replaceAll(r -> env.getOrDefault(r.group(1), "?")));
        System.out.println(placeholder.matcher(template)
                .replaceAll(r -> Matcher.quoteReplacement(env.getOrDefault(r.group(1), "?"))));

        // 3. results(): every match as a stream.
        Map<String, Integer> pairs = Pattern.compile("(?<key>[a-z]+)=(?<value>\\d+)").matcher("a=1, bb=22, c=333")
                .results()
                .collect(Collectors.toMap(r -> r.group("key"), r -> Integer.parseInt(r.group("value")),
                        Integer::sum, TreeMap::new));
        System.out.println(pairs);

        // 4. Two predicates, one pattern, two meanings.
        Pattern digits = Pattern.compile("\\d+");
        List<String> items = List.of("42", "abc7", "007", "x");
        System.out.println("asPredicate (find):       " + items.stream().filter(digits.asPredicate()).toList());
        System.out.println("asMatchPredicate (whole): " + items.stream().filter(digits.asMatchPredicate()).toList());

        // 5. splitAsStream
        System.out.println(Pattern.compile("\\s*[,;]\\s*").splitAsStream("red , green;blue,  yellow").toList());

        // 6. Lookahead: several independent rules at the same position, so the order does not matter.
        Pattern strong = Pattern.compile("(?=.*\\d)(?=.*\\p{Lower})(?=.*\\p{Upper})(?=.*[^\\p{Alnum}]).{10,}");
        for (String password : List.of("Tr0ub4dor&3", "correct horse battery", "Sh0rt&Ok", "NoDigits&Here")) {
            System.out.printf("%-22s %b%n", password, strong.matcher(password).matches());
        }

        // 7. Lookbehind plus lookahead: insert a comma wherever a digit is followed by a multiple of three digits.
        Pattern thousands = Pattern.compile("(?<=\\d)(?=(?:\\d{3})+\\b)");
        for (String number : List.of("999", "1000", "1234567", "1234567.891234")) {
            System.out.println(number + " -> " + thousands.matcher(number).replaceAll(","));
        }

        // 8. \R is every kind of linebreak, String.lines() only knows three of them.
        String mixed = "unix\nwindows\r\nold mac\rnext\u0085line\u2028sep";
        System.out.println("split(\\R): " + Arrays.toString(mixed.split("\\R")) + ", lines(): " + mixed.lines().count());

        // 9. Flags inside the pattern, and (?x) with comments.
        Pattern iso = Pattern.compile("""
                (?x)                          # comments mode: whitespace and # comments are ignored
                (?<year>\\d{4})  -            # four digit year
                (?<month>0[1-9]|1[0-2])  -    # 01 to 12
                (?<day>0[1-9]|[12]\\d|3[01])  # 01 to 31
                """);
        System.out.println(iso.matcher("2026-10-03").matches() + " " + iso.matcher("2026-13-03").matches());
        System.out.println("(?i) is ASCII only: " + Pattern.matches("(?i)caf\u00e9", "CAF\u00c9"));
        System.out.println("(?iu) is Unicode:   " + Pattern.matches("(?iu)caf\u00e9", "CAF\u00c9"));
        System.out.println("scoped (?i:...):    " + Pattern.matches("(?i:hello) World", "HELLO World")
                + " " + Pattern.matches("(?i:hello) World", "HELLO world"));
    }
}
```

Output:

```text output
WARN from mo on 2026-10-03
released 03.10.2026
quoted: it's fine
quoted: no
hi mo, home is C:Usersmo, shell is ?
hi mo, home is C:\Users\mo, shell is ?
{a=1, bb=22, c=333}
asPredicate (find):       [42, abc7, 007]
asMatchPredicate (whole): [42, 007]
[red, green, blue, yellow]
Tr0ub4dor&3            true
correct horse battery  false
Sh0rt&Ok               false
NoDigits&Here          false
999 -> 999
1000 -> 1,000
1234567 -> 1,234,567
1234567.891234 -> 1,234,567.891,234
split(\R): [unix, windows, old mac, next, line, sep], lines(): 4
true false
(?i) is ASCII only: false
(?iu) is Unicode:   true
scoped (?i:...):    true false
```

## Catastrophic backtracking, measured safely

A backtracking engine tries alternatives and returns to earlier choices when a later part fails. When two parts of a pattern can split the same text in many ways, and the overall match is doomed (here: the closing quote is missing), the engine tries every split. Each extra character can double the work.

Timing that is a good way to freeze a test runner, so the next program measures it by *counting*. The input is wrapped in a `CharSequence` that counts how often the engine reads a character. The count is the same on every run, and the same wrapper doubles as the only real defense the JDK offers: it can throw when a budget is exceeded, because `Matcher` has no timeout of its own.

```java run
import java.util.regex.*;

public class Backtracking {

    /** The regex engine reads input through charAt, so counting (or limiting) the calls measures its work. */
    static final class Counting implements CharSequence {
        private final String text;
        private final long budget;
        long reads;

        Counting(String text, long budget) { this.text = text; this.budget = budget; }

        public int length() { return text.length(); }
        public char charAt(int index) {
            if (++reads > budget) throw new IllegalStateException("regex budget exceeded after " + budget + " reads");
            return text.charAt(index);
        }
        public CharSequence subSequence(int start, int end) { return text.subSequence(start, end); }
        @Override public String toString() { return text; }
    }

    static long reads(Pattern pattern, int n) {
        Counting input = new Counting("'" + "a".repeat(n) + "!", Long.MAX_VALUE);   // the quote is never closed
        pattern.matcher(input).matches();
        return input.reads;
    }

    public static void main(String[] args) {
        Pattern noBackref = Pattern.compile("^['\"](\\w+\\s?)*$");
        Pattern backref   = Pattern.compile("^(['\"])(\\w+\\s?)*\\1$");
        Pattern possessive = Pattern.compile("^(['\"])(?:\\w+\\s?)*+\\1$");
        Pattern atomic    = Pattern.compile("^(['\"])(?>\\w+\\s?)*\\1$");

        System.out.printf("%4s %12s %12s %12s %12s%n", "n", "no backref", "backref", "possessive", "atomic");
        for (int n : new int[] {8, 12, 16, 20, 22}) {
            System.out.printf("%4d %12d %12d %12d %12d%n", n,
                    reads(noBackref, n), reads(backref, n), reads(possessive, n), reads(atomic, n));
        }

        // The budget turns a runaway match into an exception you can handle.
        try {
            backref.matcher(new Counting("'" + "a".repeat(40) + "!", 1_000_000)).matches();
        } catch (IllegalStateException e) {
            System.out.println(e.getMessage());
        }

        // Same text, same answer on real input: the fixes did not change what the pattern accepts.
        for (Pattern p : new Pattern[] {backref, possessive, atomic}) {
            System.out.print(p.matcher("'hello big world'").matches() + " ");
        }
        System.out.println();

        // But a possessive quantifier is not a free speed-up: it never gives characters back.
        System.out.println("\".*\" matches \"abc\":  " + Pattern.matches("\".*\"", "\"abc\""));
        System.out.println("\".*+\" matches \"abc\": " + Pattern.matches("\".*+\"", "\"abc\""));
    }
}
```

Output:

```text output
   n   no backref      backref   possessive       atomic
   8           97         1279           14           16
  12          193        20479           18           20
  16          321       327679           22           24
  20          481      5242879           26           28
  22          573     20971519           28           30
regex budget exceeded after 1000000 reads
true true true
".*" matches "abc":  true
".*+" matches "abc": false
```

And now the clock. These numbers are wall time, so the block is flagged `nondeterministic`: they differ on every run and machine, and I kept `n` small enough that the slowest case takes well under a second.

```java run nondeterministic
import java.util.regex.*;

public class BacktrackingTimes {

    static long millis(Pattern pattern, int n) {
        String input = "'" + "a".repeat(n) + "!";
        long start = System.nanoTime();
        pattern.matcher(input).matches();
        return (System.nanoTime() - start) / 1_000_000;
    }

    public static void main(String[] args) {
        Pattern backref = Pattern.compile("^(['\"])(\\w+\\s?)*\\1$");
        Pattern possessive = Pattern.compile("^(['\"])(?:\\w+\\s?)*+\\1$");
        for (int n : new int[] {16, 18, 20, 22, 24}) {
            System.out.printf("n=%2d  backref %5d ms   possessive %d ms%n", n, millis(backref, n), millis(possessive, n));
        }
    }
}
```

Output (one sample, **times vary**):

```text output
n=16  backref     4 ms   possessive 0 ms
n=18  backref    12 ms   possessive 0 ms
n=20  backref    23 ms   possessive 0 ms
n=22  backref    99 ms   possessive 0 ms
n=24  backref   245 ms   possessive 0 ms
```

## How it works

* **Named groups** make a pattern self-documenting and let you move groups around without renumbering. `${d}.${m}.${y}` in the replacement reorders the date, and `\k<q>` makes the closing quote match whichever quote opened the string, so `"it's fine"` survives its apostrophe.
* **`replaceAll(Function)`** replaces the `StringBuilder` loop around `appendReplacement`. The lambda gets a `MatchResult` and returns the replacement text. The catch is on the fifth line of the output, where the first version prints `C:Usersmo`: the returned string is *still a template*, so `\` escapes the next character and `$1` is a group reference. A Windows path as a replacement loses its backslashes, silently. `Matcher.quoteReplacement` makes the text literal. This is the same mini-language trap as in [064](../07-puzzlers/064-string-traps.md), just one level deeper.
* **`results()` is lazy and per-match.** It returns `Stream<MatchResult>`, so the usual stream machinery (filter, group, collect to a sorted map) applies. Each `MatchResult` is an immutable snapshot, unlike the `Matcher` itself, which is why it is safe to keep around.
* **`asPredicate()` uses `find()`**, so `"abc7"` passes. **`asMatchPredicate()` uses `matches()`**, so only `"42"` and `"007"` pass. The names are not obvious, and mixing them up is a bug that tests rarely catch.
* **`splitAsStream`** is a lazy `split`. Like `split`, it drops trailing empty strings. See [064](../07-puzzlers/064-string-traps.md) for what `split` itself does with limits.
* **Lookahead is a zero-width test.** In the password rule, four lookaheads are all asked at position 0 and none of them consumes anything, so they combine as a logical AND in any order, and `.{10,}` finally consumes the string. `correct horse battery` fails two of the four (no digit, no capital letter; the spaces satisfy the symbol lookahead, because `[^\p{Alnum}]` accepts them, which your policy may or may not want), `Sh0rt&Ok` fails the length check, and `NoDigits&Here` fails only the digit lookahead. Add a rule by adding a lookahead.
* **Lookbehind is a zero-width test of what lies before.** The thousands separator pattern matches at a *position*, not on characters: any place after a digit where the rest of the digits is a multiple of three. `replaceAll(",")` inserts at those positions. The last number shows the catch: it was written for whole numbers, so the fractional digits get a comma too.
* **`\R`** matches `\r\n` as one unit and also the rarer `\u000B`, `\u000C`, `\u0085`, `\u2028` and `\u2029`, so `split("\\R")` finds six pieces where `String.lines()`, which only knows `\n`, `\r` and `\r\n`, finds four.
* **`(?x)` plus a text block** gives a regex you can read. Whitespace is ignored and `#` starts a comment until the end of the line. In the same spirit, `(?i)` is scoped by `(?i:...)`, and by default it only folds ASCII: `é` and `É` only match each other with `(?iu)` (the `false` and `true` on the output lines for the two flags).
* **Why the counts explode.** Without a backreference, current JDKs remember positions where a greedy group loop already failed and do not retry them. That is why the `no backref` column grows slowly (checked on JDK 17 and 25). The JDK's own source says this optimization is only applied "IF there is no group ref in this pattern". Add one backreference *anywhere* and the safety net is off: every way to cut `aaaa` into groups is tried, and the count grows by a factor of 16 for every four extra characters, which is a factor of 2 per character.
* **The fixes tell the engine not to go back.** `(?:\w+\s?)*+` is a possessive loop: whatever it consumes, it keeps. `(?>\w+\s?)*` is an atomic group per iteration: once an iteration matched, the engine never re-splits it. Both fail fast on the bad input, and both still accept the good input. That is safe here because the closing quote can never be matched by `\w` or `\s`, so there is nothing useful to give back.

## Gotchas

* **Possessive quantifiers change the meaning when giving back was needed.** `".*+"` can never match, because `.*+` swallows the closing quote and refuses to return it (last two lines of the output). Use them only where you can argue that the following part cannot match what you consume.
* **`Pattern` is thread-safe, `Matcher` is not.** Compile once into a `static final Pattern`, create a `Matcher` per use. `String.matches`, `replaceAll` and `split` recompile the pattern on every call.
* **`matches()` needs the whole string, `find()` a part, `lookingAt()` a prefix.** Anchors (`^`, `$`) change meaning with `(?m)`: they then match at every line.
* **`.` does not match a newline** unless `(?s)` is on, which silently breaks `.*` across lines and `.{10,}` for passwords with a newline in them.
* **User input in a pattern needs `Pattern.quote`**, and user input in a replacement needs `Matcher.quoteReplacement`. A regex built from raw input is also a denial of service waiting to happen, because the attacker chooses the backtracking.
* **A counting `CharSequence` is a guard, not a fix.** It stops runaway work after a budget, and it costs a virtual call per character. The real fix is a pattern without ambiguity, or no regex at all for simple jobs: `String.split`, `indexOf` and `strip` are faster and cannot backtrack.
* **Numbers and dates are not a regex job.** The thousands pattern above is a demonstration of lookarounds. Use `NumberFormat`, `String.format("%,d")` and `java.time` for the real thing.

## When to use it (and when not to)

Use named groups and `results()` whenever you pull structured values out of text: log lines, identifiers, simple formats. Use lookarounds for "this, but only when surrounded by that". Use `(?x)` in a text block for any pattern longer than a line.

Do not write a regex for nested or recursive formats (HTML, JSON, source code: write a parser, see [028](../03-build-it-yourself/028-parser-combinators.md)), and do not put a pattern from untrusted input, or one with ambiguous nested quantifiers, in front of untrusted text without a budget. Regexes for validation of complex formats (email addresses, URLs) are almost always wrong in some corner and better replaced by `java.net.URI` or a verification mail.

## Related

* [029 · A Regex Engine in 30 Lines](../03-build-it-yourself/029-regex-engine.md), to see why backtracking happens
* [064 · String Traps](../07-puzzlers/064-string-traps.md), on `split` and `replaceAll`
* [044 · Text Blocks: Beyond Multiline Strings](../05-modern-language/044-text-blocks.md), for readable patterns
* [028 · Parser Combinators: Grammars as Code](../03-build-it-yourself/028-parser-combinators.md), for formats a regex cannot handle

## Sources

* [`java.util.regex.Pattern` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/regex/Pattern.html), the reference for every construct above
* [`java.util.regex.Matcher` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/regex/Matcher.html), for `replaceAll(Function)`, `results()` and `quoteReplacement`
* [`java.util.regex.MatchResult` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/regex/MatchResult.html)
* Russ Cox, [Regular Expression Matching Can Be Simple And Fast](https://swtch.com/~rsc/regexp/regexp1.html) (2007), on why backtracking engines go exponential
* [OWASP: Regular expression Denial of Service](https://owasp.org/www-community/attacks/Regular_expression_Denial_of_Service_-_ReDoS)
