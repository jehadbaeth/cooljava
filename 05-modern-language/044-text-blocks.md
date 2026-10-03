# 044 · Text Blocks: Beyond Multiline Strings

> Three quotes, and the compiler quietly decides which of your spaces were indentation and which were content. Learn its rule and you can put exactly the whitespace you want into a string.

**Since:** Java 15 · **Category:** [Modern Language Features](../README.md#modern-language-features) · **Level:** Beginner · **Verdict:** ✅ Production

## The problem

Before text blocks, any SQL, JSON or HTML in Java looked like this:

```java
String query = "SELECT id, name\n" +
               "  FROM users\n" +
               " WHERE active = true\n" +
               " ORDER BY name\n";
```

Quotes, `\n` and `+` on every line, and an escaped `\"` for every quote in the JSON. Text blocks fix that, and everyone knows the basic form. Fewer people know the precise rule for indentation, so they are surprised when a block comes out indented by four spaces, missing its trailing spaces, or with a newline they did not expect.

## The trick

A text block starts with `"""` and a line break, and ends with `"""`. The compiler then applies three steps, in this order (JLS §3.10.6):

1. **Normalize line endings** to `\n`, whatever the source file used.
2. **Strip incidental indentation.** Find the smallest indentation over all non-blank content lines *and the line with the closing delimiter*, and remove that many whitespace characters from every line. Trailing whitespace on each line is removed too.
3. **Translate escape sequences**, including two that only make sense here: `\s` (a single space) and `\` at the end of a line (no newline).

Step 2 is the one to internalize: **the closing `"""` is a ruler.** Put it under the content and you get no indentation; move it left and every line gains that much; put it at the end of the last line and the string has no final newline. Step 3 coming last explains the escape tricks: `\s` is not whitespace yet when trailing spaces are stripped, so it survives and protects the spaces in front of it.

## Full example

The `show` helper prints every line between `|` markers, with spaces as `.` and tabs as `[TAB]`, so the exact whitespace is visible.

```java run
public class TextBlocks {

    // Prints a string so every character counts: spaces as '.', tabs as [TAB], line ends as '|'.
    static void show(String label, String s) {
        System.out.println(label);
        String body = s.endsWith("\n") ? s.substring(0, s.length() - 1) : s;
        for (String line : body.split("\n", -1)) {
            System.out.println("  |" + line.replace(" ", ".").replace("\t", "[TAB]") + "|");
        }
        System.out.println(s.endsWith("\n") ? "  (ends with a newline)" : "  (no final newline)");
    }

    public static void main(String[] args) {
        // 1. The closing delimiter decides how much indentation is incidental.
        String flush = """
                SELECT id
                  FROM users
                """;
        String shiftedLeft = """
                SELECT id
                  FROM users
            """;
        String shiftedRight = """
                SELECT id
                  FROM users
                        """;
        String sameLine = """
                SELECT id
                  FROM users""";
        show("delimiter flush with the content", flush);
        show("delimiter 4 columns to the left", shiftedLeft);
        show("delimiter 8 columns to the right", shiftedRight);
        show("delimiter on the last content line", sameLine);

        // 2. Trailing spaces are stripped unless \s pins them; a backslash joins lines.
        String columns = """
                red  \s
                green\s
                blue \s
                """;
        String longLine = """
                Text blocks keep newlines, \
                unless you ask them \
                not to.\
                """;
        show("\\s keeps trailing spaces", columns);
        show("backslash continues the line", longLine);

        // 3. Embedding: JSON with formatted(), and escaped triple quotes for Python.
        String json = """
                {
                  "name": "%s",
                  "age": %d,
                  "tags": ["%s", "%s"]
                }
                """.formatted("Ada", 36, "math", "engines");
        System.out.print(json);

        String python = """
                def greet(name):
                    \"""Say hello, politely.\"""
                    return f"Hello, {name}!"
                """;
        System.out.print(python);

        // 4. The same algorithms at runtime, for strings that did not come from source code.
        String template = "    Dear %s,\n    \\tyour order has shipped.\n    Regards";
        show("stripIndent(), translateEscapes(), formatted()",
                template.stripIndent().translateEscapes().formatted("Ada"));
        show("stripIndent() on the same input plus a final newline", (template + "\n").stripIndent());

        // 5. Indentation is counted in characters, not columns: a tab weighs as much as a space.
        String mixed = "\tif (ready) {\n        launch();\n\t}";
        show("one tab and eight spaces, after stripIndent()", mixed.stripIndent());

        // 6. formatted() is not an encoder.
        System.out.print("""
                {"name": "%s"}
                """.formatted("Ada \"The Countess\" Lovelace"));
    }
}
```

Output:

```text output
delimiter flush with the content
  |SELECT.id|
  |..FROM.users|
  (ends with a newline)
delimiter 4 columns to the left
  |....SELECT.id|
  |......FROM.users|
  (ends with a newline)
delimiter 8 columns to the right
  |SELECT.id|
  |..FROM.users|
  (ends with a newline)
delimiter on the last content line
  |SELECT.id|
  |..FROM.users|
  (no final newline)
\s keeps trailing spaces
  |red...|
  |green.|
  |blue..|
  (ends with a newline)
backslash continues the line
  |Text.blocks.keep.newlines,.unless.you.ask.them.not.to.|
  (no final newline)
{
  "name": "Ada",
  "age": 36,
  "tags": ["math", "engines"]
}
def greet(name):
    """Say hello, politely."""
    return f"Hello, {name}!"
stripIndent(), translateEscapes(), formatted()
  |Dear.Ada,|
  |[TAB]your.order.has.shipped.|
  |Regards|
  (no final newline)
stripIndent() on the same input plus a final newline
  |....Dear.%s,|
  |....\tyour.order.has.shipped.|
  |....Regards|
  (ends with a newline)
one tab and eight spaces, after stripIndent()
  |if.(ready).{|
  |.......launch();|
  |}|
  (no final newline)
{"name": "Ada "The Countess" Lovelace"}
```

## How it works

* **Closing delimiter flush with the content**: the content lines and the delimiter line share the same minimum, so all of it is removed. This is the placement the Programmer's Guide recommends for most text blocks (its guideline G4).
* **Delimiter 4 columns to the left**: the minimum is now the delimiter's indentation, so every line keeps 4 extra spaces. This is how you produce intentionally indented output.
* **Delimiter further right**: it cannot *add* stripping beyond the content's own indentation, so the result equals the flush case. Only moving left has an effect.
* **Delimiter on the last content line**: no final newline, which is the only difference between `sameLine` and `flush`. The guide prefers ending the last line with `\` instead (G12), so the delimiter stays on its own line and keeps controlling indentation.
* **`\s` pins trailing spaces.** In `red  \s` the two real spaces are not trailing (the escape follows them), and the escape becomes a third space after stripping. Three columns of exactly six characters, which `|red...|`, `|green.|` and `|blue..|` show.
* **A trailing `\` joins lines.** The source stays readable at 80 columns; the string is one line. Spaces before the backslash are kept.
* **Quotes need no escaping, triple quotes do.** The JSON contains plenty of `"` and needed none. For Python docstrings, escaping the first quote (`\"""`) is enough to stop the text block from ending.
* **`formatted(...)`** is `String.format(this, args)` as an instance method, which reads well at the end of a text block.
* **The runtime twins.** `stripIndent()` applies step 2 and `translateEscapes()` step 3 to any string, which is useful for templates loaded from files or databases. The demo strips four spaces of indentation and then turns the literal `\t` into a real tab.

## Gotchas

* **A string that ends with a newline is never stripped.** `stripIndent()` counts the last line even when it is blank, exactly like the closing delimiter line in source. After a final `\n` that last line is empty, its indentation is 0, so nothing is removed: compare the two `stripIndent()` results in the output. Trim the final newline first (or `stripTrailing()` it), then add it back.
* **Tabs count as one character.** Indentation stripping removes *characters*, not columns. One tab and eight spaces have minimum indentation 1, so `launch();` kept 7 spaces after stripping. Code that looked aligned in an editor with 8 column tabs comes out ragged. Do not mix tabs and spaces inside a text block (guideline G7 says the same).
* **Trailing whitespace vanishes silently.** Many editors also strip it on save. If trailing spaces matter (fixed width formats, Markdown line breaks), make them explicit with `\s`.
* **`formatted()` is not an encoder.** The last line of output is invalid JSON because the name contained quotes. For JSON use a JSON library; for SQL use `PreparedStatement` parameters, never `formatted()`, unless you enjoy explaining injection attacks.
* **Escapes count after stripping.** A `\t` or `\n` written as an escape is content, not indentation or a line, while stripping happens. That is what made the template example work, and it also means `\n` inside a text block does not start a new line for the indentation rule.

## When to use it (and when not to)

Use text blocks for any multi-line literal: SQL, JSON and XML fixtures in tests, HTML snippets, GraphQL queries, help texts, expected outputs. Keep the closing delimiter on its own line, flush with the content, unless you have a reason not to, and reach for `\s` and `\` when the whitespace is the point.

Do not use them to assemble data formats from untrusted input. And if a literal is long enough to scroll, it probably wants to be a resource file, loaded with `getResourceAsStream` and cleaned up with `stripIndent()`.

## Related

* [045 · Java as a Scripting Language](045-java-scripting.md), where text blocks make inline data painless
* [064 · String Traps](../07-puzzlers/064-string-traps.md)
* [097 · Regex Power Tools](../11-jdk-gems/097-regex-power-tools.md), where text blocks spare you half the backslashes

## Sources

* [JEP 378: Text Blocks](https://openjdk.org/jeps/378)
* [JLS §3.10.6: Text Blocks](https://docs.oracle.com/javase/specs/jls/se25/html/jls-3.html#jls-3.10.6), the exact stripping algorithm
* Jim Laskey and Stuart Marks, [Programmer's Guide to Text Blocks](https://openjdk.org/projects/amber/guides/text-blocks-guide)
* [`String.stripIndent()` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/String.html#stripIndent())
