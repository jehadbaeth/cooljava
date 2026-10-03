# 088 · Generating Bytecode with the Class-File API

> javac is not the only thing allowed to write class files. Since Java 24 the JDK ships its own bytecode library, and forty lines of it produce a class that never existed as source, loaded so quietly that not even `Class.forName` can find it.

**Since:** Java 24 · **Category:** [JVM, Reflection and Performance](../README.md#jvm-reflection-and-performance) · **Level:** Advanced · **Verdict:** ⚠️ Situational

## The problem

A lot of the Java ecosystem writes bytecode at runtime. Mockito and Hibernate generate subclasses, Spring generates proxies for classes, serializers and expression engines compile hot paths into real methods, agents rewrite classes as they load. Almost all of them bundle a third-party class-file library such as ASM, Byte Buddy (built on ASM) or Javassist.

That works until the JDK ships a new class-file version, which now happens every six months. The bundled library does not know version 69 yet, and your application dies with the classic `Unsupported class file major version`. The JDK had the same problem internally: it carried its own copy of ASM to generate lambda classes, and that copy could not support a JDK's new class-file features until after that JDK was finished.

## The trick

`java.lang.classfile` (JEP 484, final in Java 24) is a class-file library that ships with the JDK and is updated with it. It has three verbs: **parse** bytes into an immutable model, **build** bytes from a lambda-driven builder, and **transform** one into the other.

```java
byte[] bytes = ClassFile.of().build(ClassDesc.of("Generated"), clazz -> clazz
        .withInterfaceSymbols(ClassDesc.of("java.util.function.IntUnaryOperator"))
        .withMethodBody("applyAsInt", MethodTypeDesc.of(CD_int, CD_int), ClassFile.ACC_PUBLIC, code -> code
                .iload(1).iload(1).imul().iconst_1().iadd().ireturn()));   // x * x + 1
```

Pair it with **hidden classes** (JEP 371, Java 15): `Lookup.defineHiddenClass(bytes, ...)` loads bytes as a class that no class loader can find by name. It can be unloaded as soon as nothing references it, and it gets a `Lookup` with full access to itself. That is precisely what the JDK does for every lambda you write.

## Full example

```java run
import java.lang.classfile.*;
import java.lang.constant.*;
import java.lang.invoke.MethodHandle;
import java.lang.invoke.MethodHandles;
import java.util.function.IntUnaryOperator;
import java.util.stream.*;

import static java.lang.constant.ConstantDescs.*;
import static java.lang.invoke.MethodType.methodType;

public class BytecodeDemo {

    /** Builds: public final class Generated implements IntUnaryOperator { ... } */
    static byte[] generate() {
        // A hidden class must live in the lookup class's package: the unnamed package here.
        ClassDesc generated = ClassDesc.of("Generated");
        return ClassFile.of().build(generated, clazz -> clazz
                .withFlags(ClassFile.ACC_PUBLIC | ClassFile.ACC_FINAL)
                .withInterfaceSymbols(ClassDesc.of("java.util.function.IntUnaryOperator"))

                // public Generated() { super(); }
                .withMethodBody(INIT_NAME, MTD_void, ClassFile.ACC_PUBLIC, code -> code
                        .aload(0)
                        .invokespecial(CD_Object, INIT_NAME, MTD_void)
                        .return_())

                // public int applyAsInt(int x) { return x * x + 1; }
                .withMethodBody("applyAsInt", MethodTypeDesc.of(CD_int, CD_int), ClassFile.ACC_PUBLIC, code -> code
                        .iload(1)
                        .iload(1)
                        .imul()
                        .iconst_1()
                        .iadd()
                        .ireturn())

                // public static long factorial(int n) { long r = 1; while (n > 1) { r *= n; n--; } return r; }
                .withMethodBody("factorial", MethodTypeDesc.of(CD_long, CD_int),
                        ClassFile.ACC_PUBLIC | ClassFile.ACC_STATIC, code -> {
                    int n = code.parameterSlot(0);
                    int result = code.allocateLocal(TypeKind.LONG);
                    Label loop = code.newLabel();
                    Label done = code.newLabel();
                    code.lconst_1().lstore(result)
                        .labelBinding(loop)
                        .iload(n).iconst_1().if_icmple(done)          // while (n > 1)
                        .lload(result).iload(n).i2l().lmul().lstore(result)
                        .iinc(n, -1)
                        .goto_(loop)
                        .labelBinding(done)
                        .lload(result).lreturn();
                }));
    }

    static void listMethods(ClassModel model, boolean withCode) {
        System.out.println(model.thisClass().asInternalName().replace('/', '.') + ":");
        for (MethodModel method : model.methods()) {
            String flags = method.flags().flags().stream()
                    .map(f -> f.name().toLowerCase()).sorted().collect(Collectors.joining(" "));
            System.out.println("  " + method.methodName().stringValue()
                    + method.methodTypeSymbol().displayDescriptor() + "  [" + flags + "]");
            if (withCode) {
                method.code().ifPresent(code -> System.out.println("      " + code.elementStream()
                        .filter(e -> e instanceof Instruction)
                        .map(e -> ((Instruction) e).opcode().name().toLowerCase())
                        .collect(Collectors.joining(" "))));
            }
        }
    }

    public static void main(String[] args) throws Throwable {
        byte[] bytes = generate();
        System.out.println("generated " + bytes.length + " bytes, verifier errors: " + ClassFile.of().verify(bytes));

        // Load it as a hidden class: no name in any class loader, unloadable when unreachable.
        MethodHandles.Lookup lookup = MethodHandles.lookup().defineHiddenClass(bytes, true);
        Class<?> cls = lookup.lookupClass();
        System.out.println("hidden? " + cls.isHidden() + ", implements IntUnaryOperator? "
                + IntUnaryOperator.class.isAssignableFrom(cls));
        try {
            Class.forName(cls.getName());
        } catch (ClassNotFoundException e) {
            System.out.println("Class.forName finds it? no");
        }

        IntUnaryOperator op = (IntUnaryOperator) lookup.findConstructor(cls, methodType(void.class)).invoke();
        System.out.println("x * x + 1 for 1..5: " + IntStream.rangeClosed(1, 5).map(op).boxed().toList());

        MethodHandle factorial = lookup.findStatic(cls, "factorial", methodType(long.class, int.class));
        System.out.println("factorial(20) = " + (long) factorial.invokeExact(20));

        // You are the compiler now: nothing stops you from returning a long as an int.
        byte[] broken = ClassFile.of().build(ClassDesc.of("Broken"), clazz -> clazz
                .withMethodBody("answer", MethodTypeDesc.of(CD_int), ClassFile.ACC_PUBLIC | ClassFile.ACC_STATIC,
                        code -> code.lconst_1().ireturn()));
        ClassFile.of().verify(broken).forEach(e -> System.out.println("broken: " + e.getMessage()));

        // Parsing: our own bytes, and a class from the JDK itself.
        listMethods(ClassFile.of().parse(bytes), true);
        byte[] jdkBytes;
        try (var in = Object.class.getResourceAsStream("/java/util/function/IntUnaryOperator.class")) {
            jdkBytes = in.readAllBytes();
        }
        listMethods(ClassFile.of().parse(jdkBytes), false);
    }
}
```

Output:

```text output
generated 313 bytes, verifier errors: []
hidden? true, implements IntUnaryOperator? true
Class.forName finds it? no
x * x + 1 for 1..5: [2, 5, 10, 17, 26]
factorial(20) = 2432902008176640000
broken: Bad type on operand stack in Broken::answer() @1 (integer_type is not assignable from long2_type)
Generated:
  <init>()void  [public]
      aload_0 invokespecial return
  applyAsInt(int)int  [public]
      iload_1 iload_1 imul iconst_1 iadd ireturn
  factorial(int)long  [public static]
      lconst_1 lstore_1 iload_0 iconst_1 if_icmple lload_1 iload_0 i2l lmul lstore_1 iinc goto lload_1 lreturn
java.util.function.IntUnaryOperator:
  applyAsInt(int)int  [abstract public]
  compose(IntUnaryOperator)IntUnaryOperator  [public]
  andThen(IntUnaryOperator)IntUnaryOperator  [public]
  identity()IntUnaryOperator  [public static]
  lambda$identity$0(int)int  [private static synthetic]
  lambda$andThen$0(IntUnaryOperator,int)int  [private synthetic]
  lambda$compose$0(IntUnaryOperator,int)int  [private synthetic]
```

## How it works

* **Symbols, not strings.** `ClassDesc` and `MethodTypeDesc` (from `java.lang.constant`, Java 12) describe types without loading them. `MethodTypeDesc.of(CD_long, CD_int)` is the descriptor `(I)J`, which `displayDescriptor()` prints back as `(int)long`. The constant pool, the thing every ASM user has fought with, is filled in for you.
* **The builder mirrors the bytecode.** Each `CodeBuilder` method is one instruction, and `iload(1)` already picks the compact `iload_1` encoding, as the parsed listing shows. `parameterSlot(0)` and `allocateLocal(TypeKind.LONG)` hand out local variable slots (a `long` takes two), and `Label` plus `labelBinding` give you jump targets.
* **Stack maps are computed for you.** Since Java 7 the verifier requires a `StackMapTable` describing the types at every branch target, and computing it by hand is the most tedious part of writing bytecode. `ClassFile.of()` generates it by default, which is why the `factorial` loop verifies with no extra work.
* **`verify` before you load.** `ClassFile.of().verify(bytes)` runs the same checks the JVM will run and returns a list of `VerifyError`s. An empty list for `Generated`, and a clear "integer_type is not assignable from long2_type" for `Broken`, where the JVM's own message at load time would have been a longer dump.
* **Hidden classes.** `defineHiddenClass(bytes, true)` defines and initializes the class in the *lookup class's* package and loader, which is why the generated name is the unqualified `Generated`. The returned `Lookup` has full privileges on the new class, so `findConstructor` and `findStatic` turn it into an `IntUnaryOperator` and a `MethodHandle`. Its real name gets a `/0x...` suffix that is not a valid binary name, so `Class.forName` cannot find it, and it can be unloaded once unreachable.
* **Parsing reads anything.** The last block is the JDK's own `IntUnaryOperator`. The bodies of its default methods `compose` and `andThen` are lambdas, and here you can see where they went: private synthetic methods like `lambda$compose$0`, compiled into the interface itself.

## Gotchas

* **You are the compiler now.** The API checks that the class file is well formed, not that your instruction sequence makes sense. `lconst_1` then `ireturn` builds without complaint and only `verify` (or the class loader) objects. Write the Java equivalent in a comment above each method, as the example does, and test generated code like any other code.
* **The package rule.** A hidden class must be in the same package as the `Lookup` that defines it. Generating `com.acme.Generated` from a lookup in `org.example` fails with `IllegalArgumentException`.
* **Pick the right class options.** `ClassOption.NESTMATE` gives the hidden class private access to the lookup class's nest (lambdas use this), and `ClassOption.STRONG` ties its lifetime to the class loader instead of letting it be unloaded early.
* **Class generation is not free.** Building, verifying and defining a class costs far more than a method call. Generate once per shape, cache the result, and do not define a class per request.
* **Debugging is on you.** No source file and no line numbers unless you emit them. When something goes wrong, write the bytes to a temp file and run `javap -c -p` on it, or print `ClassModel.toDebugString()`.
* **Version gate.** The API is final from Java 24. On Java 22 and 23 it was a preview API, so the example does not compile there without `--enable-preview`, and the details changed between previews.

## When to use it (and when not to)

Reach for the Class-File API when you are writing the kind of tool that used to bundle ASM: a framework that generates adapters, a compiler for a small language or rule engine, a Java agent, a build plugin that rewrites class files. Shipping with the JDK means it always understands the class files of the JDK it runs on, and that is the main reason to prefer it.

For application code, keep writing Java. If you need interception, a [dynamic proxy](085-dynamic-proxies.md) or a library like Byte Buddy gives you far higher-level tools. If you need fast generic access, [`LambdaMetafactory`](086-methodhandles-lambdametafactory.md) builds the hidden class for you. And if you want to generate code at runtime but think in source, [compile Java at runtime](090-runtime-compilation-jshell.md) instead.

## Related

* [085 · Dynamic Proxies: Implementing Interfaces at Runtime](085-dynamic-proxies.md), generated classes without writing bytecode
* [086 · MethodHandles and LambdaMetafactory: Reflection at Full Speed](086-methodhandles-lambdametafactory.md), which defines hidden classes for every lambda
* [090 · Compile and Run Java at Runtime](090-runtime-compilation-jshell.md), the source-level way to make classes on the fly

## Sources

* [JEP 484: Class-File API](https://openjdk.org/jeps/484)
* [JEP 371: Hidden Classes](https://openjdk.org/jeps/371)
* [`java.lang.classfile` package summary (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/classfile/package-summary.html)
* [`MethodHandles.Lookup` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/invoke/MethodHandles.Lookup.html), see `defineHiddenClass`
* [JVM Specification, Chapter 4: The class File Format](https://docs.oracle.com/javase/specs/jvms/se25/html/jvms-4.html)
