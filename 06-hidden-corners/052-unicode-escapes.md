# 052 · Unicode Escapes: Hiding Code in Comments

> Java turns `\u000d` into a carriage return before it decides what is a comment, so a comment can end in the middle of a line and the rest of that line is code. javac does not warn, and neither does a review that skips comments.

**Since:** Java 8 · **Category:** [Hidden Corners and Party Tricks](../README.md#hidden-corners-and-party-tricks) · **Level:** Intermediate · **Verdict:** 🧪 Party trick

Unicode escapes have been in the language since 1.0, so the trick works on every Java version. The badge says 8 because that is the oldest release a current javac can target.

## The problem

You read a source file by skipping comments. The compiler does not read it that way. Before it looks for comments, strings or keywords, it makes a pass over the raw text and replaces every `\uXXXX` with the character it names. Only then does it split the file into lines and tokens.

That order has consequences. `\u000d` is a carriage return, and a carriage return is a line terminator, so a `//` comment ends right there. What follows on the same line is no longer a comment:

```java
// this line is only a comment \u000d System.out.println("surprise");
```

Bloch and Gafter built three puzzles on this in *Java Puzzlers* (2005): Puzzle 14, "Escape Rout", Puzzle 15, "Hello Whirled" and Puzzle 16, "Line Printer". The programs below replay all three.

## The trick

Think of javac as running three steps in a fixed order:

| Step | What happens | Example |
|---|---|---|
| 1 | Unicode escapes become characters | `\u000d` turns into a carriage return |
| 2 | The text is split into lines (LF, CR or CRLF) | the carriage return ends the line |
| 3 | The text is tokenized: comments, strings, identifiers | the tail of the line is code |

Because step 1 knows nothing about step 3, an escape means the same thing everywhere: in comments, in string literals, even inside identifiers and keywords. `\u0022` is a double quote, and it ends a string literal as surely as a typed one. Two limits keep the rules from collapsing. A backslash can only start an escape when an even number of backslashes comes before it, so `\\u000d` is not an escape. And `\u` followed by anything other than four hex digits is a compile error, wherever it appears.

## Full example

Every line of output below comes from a line that looks like it should not run, or that looks like it should print something else:

```java run
public class UnicodeEscapes {

    public static void main(String[] args) {
        System.out.println("1. a comment that is not one");
        // this is only a note \u000d System.out.println("  I ran, and I was in a comment");
        System.out.println("  the line after the comment");

        System.out.println("2. an even number of backslashes is not an escape");
        // this is really a comment \\u000d System.out.println("  you will never see this");
        System.out.println("  nothing hidden ran");

        System.out.println("3. Escape Rout, Java Puzzlers puzzle 14");
        System.out.println("a\u0022.length() + \u0022b".length());

        System.out.println("4. escapes work in identifiers and keywords too");
        int \u0061bc = 7;
        System.out.println("  abc = " + abc);
        \u0053ystem.out.println("  the S of System was an escape");

        System.out.println("5. odd corners from JLS 3.3");
        char a = '\uuuu0041';
        char backslash = '\u005c\u005c';
        String newline = "x\u005cny";
        System.out.println("  any number of u: " + a);
        System.out.println("  two escaped backslashes make one character: " + (int) backslash);
        System.out.println("  an escaped backslash can start a string escape: length " + newline.length());
    }
}
```

Output:

```text output
1. a comment that is not one
  I ran, and I was in a comment
  the line after the comment
2. an even number of backslashes is not an escape
  nothing hidden ran
3. Escape Rout, Java Puzzlers puzzle 14
2
4. escapes work in identifiers and keywords too
  abc = 7
  the S of System was an escape
5. odd corners from JLS 3.3
  any number of u: A
  two escaped backslashes make one character: 92
  an escaped backslash can start a string escape: length 3
```

Line 3 prints 2, not the length of a long string. After translation the compiler sees `"a".length() + "b".length()`: the first `\u0022` closes a one-character string and the second opens another one.

A line terminator can also break the build. The first program is adapted from Puzzle 16. The comment holds an escaped linefeed, so the comment ends early and `is Unicode representation of linefeed (LF)` becomes code:

```java compile-fail
public class LinePrinter {
    public static void main(String[] args) {
        // Note: \u000a is Unicode representation of linefeed (LF)
        char c = 0x000a;
        System.out.print(c);
    }
}
```

```text compile-error
LinePrinter.java:3: error: ';' expected
        // Note: \u000a is Unicode representation of linefeed (LF)
                                  ^
LinePrinter.java:3: error: ';' expected
        // Note: \u000a is Unicode representation of linefeed (LF)
                                                    ^
LinePrinter.java:3: error: ';' expected
        // Note: \u000a is Unicode representation of linefeed (LF)
                                                                  ^
3 errors
```

The same translation happens inside a string literal, where a raw line break is not allowed:

```java compile-fail
public class SplitString {
    public static void main(String[] args) {
        String s = "line1\u000aline2";
        System.out.println(s);
    }
}
```

```text compile-error
SplitString.java:3: error: unclosed string literal
        String s = "line1\u000aline2";
                   ^
SplitString.java:3: error: unclosed string literal
        String s = "line1\u000aline2";
                                    ^
SplitString.java:3: error: not a statement
        String s = "line1\u000aline2";
                               ^
3 errors
```

And the most common accident, the idea behind Puzzle 15: a Windows path in a comment. `\u` must be followed by four hex digits, even in a comment, so `C:\users` stops the build:

```java compile-fail
public class WindowsPath {
    // config lives in C:\users\ada\app.properties
    public static void main(String[] args) {
        System.out.println("hi");
    }
}
```

```text compile-error
WindowsPath.java:2: error: illegal unicode escape
    // config lives in C:\users\ada\app.properties
                           ^
1 error
```

## Spotting it in review

The escape `\u000d` is plain ASCII in the file, so a diff shows it. What fails is the human: people read a `//` line as inert. The compiler will not help either. javac 25 has no lint category for escapes or for bidirectional characters, and compiles the first program with every warning enabled and no output (both commands ran on JDK 25):

```shell
javac --help-lint | grep -i -c -e unicode -e bidi
javac -Xlint:all UnicodeEscapes.java; echo "javac exit code: $?"
```

```text
0
javac exit code: 0
```

A check you can add to CI is small. This one flags escapes that denote ASCII characters (there is rarely a reason to write one), singles out the dangerous ones, and flags raw bidirectional control characters. The regex writes a backslash as `\x5C`, so the pattern never contains a backslash followed by `u`. The sample lines use real escapes for the bidirectional characters on purpose, so that this page carries no invisible characters:

```java run
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class EscapeLint {

    // An escape is a backslash with an even number of backslashes before it, then u+ and four hex digits.
    private static final Pattern ESCAPE =
            Pattern.compile("(?<!\\x5C)(?:\\x5C\\x5C)*\\x5Cu+([0-9a-fA-F]{4})");

    static boolean isBidiControl(char c) {
        return c == 0x061C || c == 0x200E || c == 0x200F
                || (c >= 0x202A && c <= 0x202E) || (c >= 0x2066 && c <= 0x2069);
    }

    static List<String> review(String[] lines) {
        List<String> findings = new ArrayList<>();
        for (int i = 0; i < lines.length; i++) {
            Matcher m = ESCAPE.matcher(lines[i]);
            while (m.find()) {
                int cp = Integer.parseInt(m.group(1), 16);
                if (cp >= 0x80) continue;          // non-ASCII escapes are legitimate
                String why;
                if (cp == 0x0A || cp == 0x0D) why = "line terminator, ends a // comment early";
                else if (cp == 0x22) why = "double quote, can end a string literal";
                else if (cp == 0x5C) why = "backslash";
                else why = "ASCII character written as an escape";
                findings.add(String.format("line %d: escape for U+%04X (%s)", i + 1, cp, why));
            }
            for (char c : lines[i].toCharArray()) {
                if (isBidiControl(c)) {
                    findings.add(String.format("line %d: bidirectional control character U+%04X", i + 1, (int) c));
                }
            }
        }
        return findings;
    }

    public static void main(String[] args) {
        String[] sample = {
            "int total = 0;",
            "// reset the counter \\u000d total = -1;",
            "String s = \"a\\u0022 + b\";",
            "String cafe = \"caf\\u00e9\";",
            "// escaped backslash, not an escape: \\\\u000d",
            "String role = \"user\u202E \u2066nimda\u2069 \u2066\";",
        };
        List<String> findings = review(sample);
        findings.forEach(System.out::println);
        System.out.println(findings.size() + " findings in " + sample.length + " lines");
    }
}
```

Output:

```text output
line 2: escape for U+000D (line terminator, ends a // comment early)
line 3: escape for U+0022 (double quote, can end a string literal)
line 6: bidirectional control character U+202E
line 6: bidirectional control character U+2066
line 6: bidirectional control character U+2069
line 6: bidirectional control character U+2066
6 findings in 6 lines
```

Line 4 of the sample is a legitimate use (an accented letter in an ASCII-only file) and is not flagged. Line 5 shows the even backslash rule, and is not flagged either.

## Trojan Source is a cousin, not the same bug

In November 2021 Nicholas Boucher and Ross Anderson of the University of Cambridge published "Trojan Source", filed as CVE-2021-42574. It abuses the Unicode bidirectional algorithm: control characters such as U+202E (right-to-left override) or U+2066 (left-to-right isolate) reorder how text is displayed without changing the order in which a compiler reads it. A reviewer sees one thing and the compiler parses another. The companion CVE-2021-42694 covers homoglyph identifiers, such as a Cyrillic `а` in place of a Latin `a`.

Be precise about the difference. The `\u000d` trick uses an old language rule, and the evidence is visible ASCII in the file. Trojan Source uses raw, invisible characters, and the CVE is filed against the Unicode specification, not against Java. The shared idea is a gap between what a reviewer reads and what the compiler sees. Rust shipped deny-by-default lints for these characters in 1.56.1. javac has nothing comparable:

```shell
printf 'public class Bidi {\n    public static void main(String[] args) {\n        String access = "user\xe2\x80\xae \xe2\x81\xa6nimda\xe2\x81\xa9 \xe2\x81\xa6";\n        System.out.println(access.length());\n    }\n}\n' > Bidi.java
javac -Xlint:all Bidi.java && echo "javac: no warnings, exit code $?"
java -cp . Bidi
```

```text
javac: no warnings, exit code 0
15
```

The `15` is the string length: the file contains the characters U+202E, U+2066 and U+2069 inside the string literal, and javac accepts it without a word (javac 17 and 27 behave the same, checked separately). The `EscapeLint` above would have flagged line 6 of its sample. GitHub's web interface now shows a warning for files with bidirectional text, but do not count on your editor: behavior varies.

## How it works

* **Translation is a separate, earlier phase.** JLS 3.3 says the compiler "first recognizes Unicode escapes in its raw input". Its output is a stream of characters in which comments and strings do not exist yet. That is why the escape in a comment is not protected by the comment.
* **Line terminators are decided after translation.** An escaped `\u000a` or `\u000d` is a real line break by the time lines are split. A `//` comment lasts until the end of the line, so it ends early.
* **Quotes and backslashes follow the same rule.** `\u0022` acts as a typed quote, which is the Escape Rout puzzle. `\u005c` becomes a backslash that can then begin a normal string escape, which is why `"x\u005cny"` contains a newline and has length 3.
* **The backslash count decides eligibility.** The JLS example is `"\\u2122=\u2122"`: the second backslash is not eligible to begin an escape, the third is. That is why `\\u000d` in the second demo stays an ordinary comment.
* **Extra `u` characters are allowed.** The grammar is `\` followed by `u {u}`, so `\uuuu0041` is the letter A. The JLS explains why: a tool that converts a source file to pure ASCII adds one more `u` to every escape that is already there and writes each non-ASCII character as an escape with a single `u`, so the conversion can be reversed without ambiguity.
* **A bad escape is an error anywhere.** `\u` followed by non-hex digits is rejected in comments too, which is how a Windows path breaks a build.

## Gotchas

* **Escapes in comments are rarely a bug and always a smell.** The usual cause is a path or an example in a comment or Javadoc that contains `\u`, which is an error, not a hidden run.
* **Generated code can contain them legitimately.** Tools that write ASCII-only source emit `\u00e9` for non-ASCII letters. Since JEP 400 (Java 18) UTF-8 is the default source encoding, so new code can contain the letter itself.
* **Escapes are still handy for invisible characters.** Writing `"\u00a0"` or `"\u200b"` makes a non-breaking space or a zero-width space visible to the reader. That is the one good use.
* **Do not trust a diff view that renders bidirectional text.** Check the raw characters in CI with a lint like the one above.
* **Escapes can also be policed by a style checker.** Checkstyle has a check named [AvoidEscapedUnicodeCharacters](https://checkstyle.org/checks/misc/avoidescapedunicodecharacters.html) that restricts Unicode escapes in general. It is aimed at escapes, not at raw bidirectional characters.

## When to use it (and when not to)

As a trick: never in production, and only to win an argument. Put an escape in a comment that ends the comment, and you have written code that a reader, a diff and a grep for `System.out` will all miss.

As a defense: reject escapes that denote ASCII characters in code review or in CI, and reject bidirectional control characters in source files outright. Neither costs a legitimate program anything. The legitimate uses of escapes, non-ASCII characters in an ASCII-only file and visible names for invisible characters, are all above U+007F.

## Related

* [051 · Weird but Legal Java Syntax](051-weird-legal-syntax.md), more grammar that does not mean what it looks like
* [049 · Labeled Blocks: break Out of Anything](049-labeled-blocks.md)
* [064 · String Traps](../07-puzzlers/064-string-traps.md), for what else happens to text you thought you understood

## Sources

* [JLS §3.3: Unicode Escapes](https://docs.oracle.com/javase/specs/jls/se25/html/jls-3.html#jls-3.3), and [§3.4: Line Terminators](https://docs.oracle.com/javase/specs/jls/se25/html/jls-3.html#jls-3.4)
* [Java Puzzlers: Traps, Pitfalls, and Corner Cases](https://catdir.loc.gov/catdir/toc/ecip0513/2005015278.html), Bloch and Gafter, table of contents (Puzzles 14, 15 and 16)
* [Trojan Source: Invisible Vulnerabilities](https://trojansource.codes/), Boucher and Anderson
* [NVD: CVE-2021-42574](https://nvd.nist.gov/vuln/detail/CVE-2021-42574)
* [Rust blog: CVE-2021-42574](https://blog.rust-lang.org/2021/11/01/cve-2021-42574/)
