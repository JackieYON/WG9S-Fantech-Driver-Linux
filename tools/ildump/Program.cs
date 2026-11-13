using System;
using System.IO;
using Mono.Cecil;

internal static class Program
{
    private static void Dump(TypeDefinition type)
    {
        Console.WriteLine("TYPE " + type.FullName);
        foreach (var field in type.Fields)
        {
            var constant = field.HasConstant ? " = " + field.Constant : "";
            Console.WriteLine("FIELD " + field.FullName + constant);
        }

        foreach (var method in type.Methods)
        {
            Console.WriteLine("METHOD " + method.FullName + " RVA=" + method.RVA.ToString("x"));
            if (method.IsPInvokeImpl)
            {
                Console.WriteLine("PINVOKE " + method.PInvokeInfo.Module.Name + " " + method.PInvokeInfo.EntryPoint);
            }
            try
            {
                if (method.HasBody)
                {
                    foreach (var instruction in method.Body.Instructions)
                        Console.WriteLine("  " + instruction);
                }
            }
            catch (Exception error)
            {
                Console.WriteLine("DECODE ERROR: " + error.Message);
            }
        }

        foreach (var nested in type.NestedTypes)
            Dump(nested);
    }

    private static int Main(string[] args)
    {
        if (args.Length < 1 || args.Length > 2)
        {
            Console.Error.WriteLine("Usage: ildump assembly [resource-directory]");
            return 2;
        }

        using var assembly = AssemblyDefinition.ReadAssembly(args[0]);
        foreach (var type in assembly.MainModule.Types)
            Dump(type);

        if (args.Length == 2)
        {
            Directory.CreateDirectory(args[1]);
            foreach (var resource in assembly.MainModule.Resources)
            {
                if (resource is EmbeddedResource embedded)
                {
                    var name = Path.GetFileName(embedded.Name.Replace('\\', '/'));
                    if (string.IsNullOrEmpty(name) || name == "." || name == "..")
                        throw new InvalidDataException("Invalid resource name");
                    File.WriteAllBytes(Path.Combine(args[1], name), embedded.GetResourceData());
                }
            }
        }
        return 0;
    }
}
