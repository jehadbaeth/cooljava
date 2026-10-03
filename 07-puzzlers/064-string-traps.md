# 064 · String Traps

> `split` throws away data you did not ask it to, `replaceAll` treats a dollar sign as a command, and in Turkey `"title".toUpperCase()` contains no ordinary capital I. The most used class in Java is also the one with the most fine print.

**Since:** Java 8 · **Category:** [Puzzlers and Gotchas](../README.md#puzzlers-and-gotchas) · **Level:** Intermediate · **Verdict:** ✅ Production

## The puzzle

Twenty-two one-liners on `String`. For each, guess the result, or the exception it throws. Three are classics from Joshua Bloch and Neal Gafter's *Java Puzzlers*: line 6 is Puzzle 20 ("What's My Class?"), line 10 is the Windows half of Puzzle 21 ("What's My Class, Take 2"), and line 14 is Puzzle 13 ("Animal Farm"). To keep the output plain ASCII, the `show` helper prints every non-ASCII character as a `\uXXXX` escape.

```java run
import java.util.*;
import java.util.concurrent.Callable;
import java.util.regex.Matcher;

public class StringTraps {

    // Prints the value, or the simple name of the exception the expression throws.
    static void show(String label, Callable<?> expression) {
        Object result;
        try {
            result = expression.call();
        } catch (Exception e) {
            result = e.getClass().getSimpleName();
        }
        if (result instanceof String[]) {
            result = Arrays.toString((String[]) result);
        }
        System.out.printf("%-48s %s%n", label, escape(String.valueOf(result)));
    }

    static String escape(String s) {
        StringBuilder sb = new StringBuilder();
        for (char c : s.toCharArray()) {
            sb.append(c < 128 ? String.valueOf(c) : String.format("\\u%04X", (int) c));
        }
        return sb.toString();
    }

    public static void main(String[] args) {
        show(" 1. \"a,b,,\".split(\",\")", () -> "a,b,,".split(","));
        show(" 2. \"a,b,,\".split(\",\", -1)", () -> "a,b,,".split(",", -1));
        show(" 3. \",a,b\".split(\",\")", () -> ",a,b".split(","));
        show(" 4. \"1.2.3\".split(\".\").length", () -> "1.2.3".split(".").length);
        show(" 5. \"a|b\".split(\"|\")", () -> "a|b".split("|"));

        show(" 6. \"cool.java\".replaceAll(\".\", \"#\")", () -> "cool.java".replaceAll(".", "#"));
        show(" 7. \"cost: X\".replaceAll(\"X\", \"$5\")", () -> "cost: X".replaceAll("X", "$5"));
        show(" 8. ...replaceAll(\"X\", quoteReplacement(\"$5\"))",
                () -> "cost: X".replaceAll("X", Matcher.quoteReplacement("$5")));
        show(" 9. \"cost: X\".replace(\"X\", \"$5\")", () -> "cost: X".replace("X", "$5"));
        show("10. \"a.b\".replaceAll(\"\\\\.\", \"\\\\\")", () -> "a.b".replaceAll("\\.", "\\"));

        final String hello = "Hello", world = "World";
        String hi = "Hello", there = "World";
        show("11. final: hello + world == \"HelloWorld\"", () -> hello + world == "HelloWorld");
        show("12. not final: hi + there == \"HelloWorld\"", () -> hi + there == "HelloWorld");
        show("13. (hi + there).intern() == \"HelloWorld\"", () -> (hi + there).intern() == "HelloWorld");
        final String pig = "length: 10";
        final String dog = "length: " + pig.length();
        show("14. \"Animals are equal: \" + pig == dog", () -> "Animals are equal: " + pig == dog);

        Locale turkish = Locale.forLanguageTag("tr");
        show("15. \"title\".toUpperCase(turkish)", () -> "title".toUpperCase(turkish));
        show("16. \"TITLE\".toLowerCase(turkish)", () -> "TITLE".toLowerCase(turkish));
        show("17. \"title\".toUpperCase(Locale.ROOT)", () -> "title".toUpperCase(Locale.ROOT));
        String strasse = "straße";
        show("18. \"stra\\u00DFe\".toUpperCase(Locale.ROOT)", () -> strasse.toUpperCase(Locale.ROOT));
        show("19. ...and its length, before and after", () -> strasse.length() + " -> " + strasse.toUpperCase(Locale.ROOT).length());

        String nothing = null;
        show("20. nothing + \"!\"", () -> nothing + "!");
        show("21. String.valueOf((Object) null)", () -> String.valueOf((Object) null));
        show("22. String.valueOf(null)", () -> String.valueOf(null));
    }
}
```

Scroll down when you have your answers.

## The answer

```text output
 1. "a,b,,".split(",")                           [a, b]
 2. "a,b,,".split(",", -1)                       [a, b, , ]
 3. ",a,b".split(",")                            [, a, b]
 4. "1.2.3".split(".").length                    0
 5. "a|b".split("|")                             [a, |, b]
 6. "cool.java".replaceAll(".", "#")             #########
 7. "cost: X".replaceAll("X", "$5")              IndexOutOfBoundsException
 8. ...replaceAll("X", quoteReplacement("$5"))   cost: $5
 9. "cost: X".replace("X", "$5")                 cost: $5
10. "a.b".replaceAll("\\.", "\\")                IllegalArgumentException
11. final: hello + world == "HelloWorld"         true
12. not final: hi + there == "HelloWorld"        false
13. (hi + there).intern() == "HelloWorld"        true
14. "Animals are equal: " + pig == dog           false
15. "title".toUpperCase(turkish)                 T\u0130TLE
16. "TITLE".toLowerCase(turkish)                 t\u0131tle
17. "title".toUpperCase(Locale.ROOT)             TITLE
18. "stra\u00DFe".toUpperCase(Locale.ROOT)       STRASSE
19. ...and its length, before and after          6 -> 7
20. nothing + "!"                                null!
21. String.valueOf((Object) null)                null
22. String.valueOf(null)                         NullPointerException
```

## Why

### Lines 1 to 3: `split` quietly drops trailing empties

`split(regex)` is defined as `split(regex, 0)`, and a limit of zero means "split as often as possible, then *remove trailing empty strings*". So `"a,b,,"` loses its last two fields, which is exactly the wrong thing for a CSV line whose last columns are empty. A negative limit keeps everything (line 2). Leading empty strings survive (line 3), so the rule is asymmetric: a leading separator gives you an extra empty string, trailing ones give you nothing.

### Lines 4 and 5: the argument is a regex

`split(".")` splits on *any character*. Every piece between two characters is empty, all of them are trailing, so all of them are removed and you get an array of length 0. `split("|")` is worse: `|` is regex alternation between two empty patterns, which matches the empty string at every position, so the string falls apart into single characters. (Since Java 8 a zero-width match at the very start no longer produces a leading empty string; on Java 7 line 5 started with an extra `""`.) Escape the separator: `split("\\.")`, `split("\\|")`, or `split(Pattern.quote(sep))` for separators that come from data.

### Lines 6 to 10: `replaceAll` has a regex on the left and a mini-language on the right

Puzzle 20 wanted to turn a class name into a path by replacing every dot with a slash, and got nothing but slashes, because `.` matches every character. Line 6 runs the same call with `#` as the replacement: nine characters in, nine `#` out. Line 7 is the other side: in the *replacement* string `$5` means "group 5 of the match", and the pattern `X` has no groups at all, so you get an `IndexOutOfBoundsException` instead of a price. A backslash is the escape character of the replacement language, and a backslash with nothing after it is an error (`IllegalArgumentException: character to be escaped is missing`, line 10). That is why Puzzle 21, which passed `File.separator` as the replacement, blew up on Windows, where it is a single backslash. Two fixes:

* `Matcher.quoteReplacement(s)` escapes `$` and `\` so the replacement is taken literally (line 8).
* `String.replace(CharSequence, CharSequence)` replaces *all* occurrences, literally, on both sides (line 9). Despite the name, `replace` is not "replace the first one": it is `replaceAll` without the regex. Use it unless you actually need a pattern.

### Lines 11 to 14: `==` on strings and constant folding

`hello` and `world` are `final` and initialized with constants, which makes them *constant variables* (JLS §4.12.4). `hello + world` is therefore a constant expression, evaluated by javac, and constant strings are interned, so it is the very same object as the literal `"HelloWorld"` (line 11). Drop the `final` and the concatenation happens at run time and produces a new object, so `==` is `false` (line 12), until you `intern()` it (line 13). The outputs of 11 and 12 differ although the values are identical: whether `==` "works" depends on a keyword two lines away.

Line 14 is a double trap. `pig.length()` is a method call, so `dog` is not a constant even though it is `final`. But that does not even matter: `+` binds tighter than `==`, so the line compares `"Animals are equal: length: 10"` with `dog`, and prints just `false`, without the "Animals are equal" part.

### Lines 15 to 19: case mapping depends on the language

Turkish has two letter i's: dotted `i`/`İ` (U+0130) and dotless `ı` (U+0131)/`I`. So in a Turkish locale the uppercase of `i` is `İ`, not `I` (line 15), and the lowercase of `I` is `ı` (line 16). Neither result equals what an English speaker expects. This is the famous "Turkish I problem": `if (command.toLowerCase().equals("title"))` works everywhere except on machines whose default locale is Turkish (or Azerbaijani), because the no-argument `toUpperCase()` and `toLowerCase()` use `Locale.getDefault()`. For identifiers, keys, protocol words and file extensions, always pass `Locale.ROOT` (line 17).

Case mapping can also change the length: German `ß` uppercases to `SS` (lines 18 and 19). Never assume `s.toUpperCase().length() == s.length()`, and never use indices from one string on its case-mapped version.

### Lines 20 to 22: null and the overloads of `valueOf`

String concatenation turns `null` into the four characters `null` (JLS §15.18.1), so a missing value becomes a plausible-looking piece of text (line 20). `String.valueOf(Object)` does the same (line 21). But `String.valueOf(null)` with a bare `null` does *not* call that method: `String` also has `valueOf(char[])`, and an array type is more specific than `Object`, so the overload rules from [061](061-boxing-overloading.md) pick the `char[]` version, which dereferences the array and throws a `NullPointerException`.

One more `null` rule: concatenation needs at least one operand of type `String`. Two bare `null`s are not enough:

```java compile-fail
public class NullPlusNull {
    public static void main(String[] args) {
        String fine = null + "!";
        String broken = null + null;
        System.out.println(fine + broken);
    }
}
```

```text compile-error
NullPlusNull.java:4: error: bad operand types for binary operator '+'
        String broken = null + null;
                             ^
  first type:  <null>
  second type: <null>
1 error
```

## Gotchas

* **`substring` used to leak memory.** Until Java 7 update 6, `substring` shared the parent's `char[]` and only stored an offset and a count. Taking a 10-character substring of a 10 MB string kept all 10 MB alive. Since 7u6 `substring` copies, which costs O(n) time but frees the parent. Old advice like `new String(s.substring(...))` is now pure waste. Since Java 9 (JEP 254, Compact Strings) a `String` stores a `byte[]` in Latin-1 or UTF-16, which halves the memory for most text.
* **`String.format`, `printf` and `toUpperCase()` all use the default locale.** `String.format("%.2f", 1.5)` prints `1,50` in Germany. Pass `Locale.ROOT` when the output is for machines.
* **`equalsIgnoreCase` is not `toLowerCase().equals`.** It compares character by character without any locale, so `"TITLE".equalsIgnoreCase("title")` is `true` even in Turkey, but it also does not know that `ß` and `SS` are the same word.
* **`trim()` is not `strip()`.** `trim` removes characters up to U+0020 only; `strip` (Java 11) removes all Unicode whitespace, such as the no-break space.
* **`intern()` is not a performance trick.** The JVM keeps interned strings in a native hash table, and every `intern()` call is a lookup in it. Interning millions of strings to save memory usually costs more than it saves, and you still compare with `equals`.

## How to stay safe

* Compare strings with `equals`, always. Constant folding makes `==` pass in tests and fail in production.
* Use `split(regex, -1)` when empty fields matter, and quote separators: `Pattern.quote(sep)`.
* Use `replace` for literal replacements; use `replaceAll` only with a real regex, and wrap untrusted replacement text in `Matcher.quoteReplacement`.
* Pass `Locale.ROOT` to `toUpperCase`, `toLowerCase` and `String.format` for anything that is not shown to a human. Error Prone's [`StringCaseLocaleUsage`](https://errorprone.info/bugpattern/StringCaseLocaleUsage) check finds the calls that do not.
* Validate inputs instead of letting `"null"` leak into strings: `Objects.requireNonNull(name)` or an explicit default.

## Related

* [061 · Boxing and Overloading Traps](061-boxing-overloading.md), for why `valueOf(null)` picks `char[]`
* [052 · Unicode Escapes: Hiding Code in Comments](../06-hidden-corners/052-unicode-escapes.md)
* [056 · "Aa" Equals "BB" (in hashCode)](../06-hidden-corners/056-hashcode-collisions.md)
* [097 · Regex Power Tools](../11-jdk-gems/097-regex-power-tools.md)

## Sources

* [`java.lang.String` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/String.html#split(java.lang.String,int)), in particular `split(String, int)` and the table of locale-sensitive case mappings under `toUpperCase(Locale)`
* [`Matcher.quoteReplacement` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/regex/Matcher.html#quoteReplacement(java.lang.String))
* [JLS §4.12.4: final Variables](https://docs.oracle.com/javase/specs/jls/se25/html/jls-4.html#jls-4.12.4) and [JLS §15.29: Constant Expressions](https://docs.oracle.com/javase/specs/jls/se25/html/jls-15.html#jls-15.29)
* [JEP 254: Compact Strings](https://openjdk.org/jeps/254)
* Joshua Bloch and Neal Gafter, *Java Puzzlers: Traps, Pitfalls, and Corner Cases* (Addison-Wesley, 2005). The [book's site](http://www.javapuzzlers.com/) has the source code of every puzzle
