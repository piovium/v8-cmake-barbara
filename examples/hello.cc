#include <libplatform/libplatform.h>
#include <v8.h>

#include <iostream>
#include <memory>

int main(int argc, char** argv) {
  (void)argc;
  v8::V8::InitializeICUDefaultLocation(argv[0]);
  auto platform = v8::platform::NewDefaultPlatform();
  v8::V8::InitializePlatform(platform.get());
  if (!v8::V8::Initialize()) return 1;
  auto allocator = std::unique_ptr<v8::ArrayBuffer::Allocator>(
      v8::ArrayBuffer::Allocator::NewDefaultAllocator());
  v8::Isolate::CreateParams params;
  params.array_buffer_allocator = allocator.get();
  auto* isolate = v8::Isolate::New(params);
  int status = 1;
  {
    v8::Isolate::Scope isolate_scope(isolate);
    v8::HandleScope handles(isolate);
    auto context = v8::Context::New(isolate);
    v8::Context::Scope context_scope(context);
    v8::TryCatch errors(isolate);
    // Exercise embedded startup data, JavaScript, and ICU when Intl is enabled.
    auto source = v8::String::NewFromUtf8Literal(isolate,
        "(() => { const a = Array.from({length: 1000}, (_, i) => i);"
        "if (typeof Intl !== 'undefined' &&"
        "new Intl.NumberFormat('en-US').format(1234) !== '1,234') throw 'ICU';"
        "return a[40] + 2; })()");
    v8::Local<v8::Script> script;
    v8::Local<v8::Value> result;
    if (v8::Script::Compile(context, source).ToLocal(&script) &&
        script->Run(context).ToLocal(&result) &&
        result->Int32Value(context).FromMaybe(0) == 42) {
      std::cout << "V8 " << v8::V8::GetVersion() << ": 42\n";
      status = 0;
    } else {
      std::cerr << "JavaScript smoke test failed\n";
    }
  }
  isolate->Dispose();
  v8::V8::Dispose();
  v8::V8::DisposePlatform();
  return status;
}
