"""Contract-level tests with synthetic APK-derived smali shapes, no app source."""

import hashlib
from pathlib import Path
import tempfile
import textwrap
import unittest

from rea_backend.harvest import harvest


class HarvestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(text).lstrip("\n"))
        return target

    def run_harvest(self):
        return harvest(self.root, "a" * 64)

    def test_discovery_overloads_and_stable_ids_are_not_tied_to_app_or_path(self):
        path = self.write("smali_classes9/strange/file.smali", '''
            .class interface abstract Lx/q;
            .super Ljava/lang/Object;
            .method public abstract read(I)Lx/Reply;
                .param p1
                    .annotation runtime Lretrofit2/http/Path;
                        value = "id"
                    .end annotation
                .end param
                .annotation runtime Lretrofit2/http/GET;
                    value = "v9/things/{id}"
                .end annotation
            .end method
            .method public abstract read(Ljava/lang/String;)Lx/Reply;
                .param p1
                    .annotation runtime Lretrofit2/http/Query;
                        value = "q"
                    .end annotation
                .end param
                .annotation runtime Lretrofit2/http/GET;
                    value = "v9/search"
                .end annotation
            .end method
        ''')
        self.write("smali/Reply.smali", ".class Lx/Reply;\n.super Ljava/lang/Object;\n.field value:I\n")
        result = self.run_harvest()
        self.assertEqual(result["coverage"]["endpoint_count"], 2)
        self.assertEqual(result["apk_sha256"], "a" * 64)
        endpoints = result["endpoints"]
        self.assertEqual(len({e["id"] for e in endpoints}), 2)
        self.assertEqual({e["method_name"] for e in endpoints}, {"read"})
        self.assertEqual({e["dex_signature"] for e in endpoints}, {"read(I)Lx/Reply;", "read(Ljava/lang/String;)Lx/Reply;"})
        for endpoint in endpoints:
            self.assertEqual(endpoint["source"]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertTrue(path.read_text().splitlines()[endpoint["source"]["line"] - 1].startswith(".method"))
            self.assertEqual(endpoint["status"], "observed")
        ids = {e["id"] for e in endpoints}
        replacement = self.root / "smali_classes2/renamed.smali"
        replacement.parent.mkdir()
        path.rename(replacement)
        replacement.write_text("\n\n" + replacement.read_text())
        self.assertEqual(ids, {e["id"] for e in self.run_harvest()["endpoints"]})

    def test_form_encoding_and_wide_register_mapping(self):
        self.write("smali/a.smali", '''
            .class public interface abstract Ldifferent/Service;
            .super Ljava/lang/Object;
            .method public abstract upload(JLjava/lang/String;D)V
                .param p1, "wide"
                .param p3
                    .annotation runtime Lretrofit2/http/Field;
                        value = "payload"
                        encoded = true
                    .end annotation
                .end param
                .param p4
                    .annotation runtime Lretrofit2/http/Query;
                        value = "ratio"
                    .end annotation
                .end param
                .annotation runtime Lretrofit2/http/FormUrlEncoded;
                .end annotation
                .annotation runtime Lretrofit2/http/POST;
                    value = "upload"
                .end annotation
            .end method
        ''')
        endpoint = self.run_harvest()["endpoints"][0]
        self.assertEqual(endpoint["media_types"], ["application/x-www-form-urlencoded"])
        self.assertEqual([p["type"] for p in endpoint["parameters"]], ["J", "Ljava/lang/String;", "D"])
        self.assertEqual(endpoint["parameters"][0]["debug_name"], "wide")
        self.assertIsNone(endpoint["parameters"][0]["location"])
        self.assertEqual(endpoint["parameters"][1]["name"], "payload")
        self.assertEqual(endpoint["parameters"][1]["location"], "form")
        self.assertIs(endpoint["parameters"][1]["encoded"], True)
        self.assertEqual(endpoint["parameters"][2]["name"], "ratio")

    def test_all_http_verbs_custom_http_and_dynamic_url(self):
        methods = []
        for verb in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
            methods.append(f'''
            .method public abstract m{verb}()V
              .annotation runtime Lretrofit2/http/{verb};
                value = "p/{verb}"
              .end annotation
            .end method
            ''')
        methods.append('''
            .method public static custom(Ljava/lang/String;)V
              .param p0
                .annotation runtime Lretrofit2/http/Url;
                .end annotation
              .end param
              .annotation runtime Lretrofit2/http/HTTP;
                method = "PROPFIND"
                hasBody = true
              .end annotation
            .end method
        ''')
        self.write("smali/verbs.smali", ".class public Lverbs/X;\n.super Ljava/lang/Object;\n" + "\n".join(methods))
        result = self.run_harvest()
        self.assertEqual(len(result["endpoints"]), 8)
        endpoint = next(e for e in result["endpoints"] if e["method_name"] == "custom")
        self.assertEqual(endpoint["http"], {"method": "PROPFIND", "path": None, "has_body": True})
        self.assertTrue(endpoint["dynamic_url"])
        self.assertFalse(any(d["code"] == "unknown_http_path" for d in result["diagnostics"]))

    def test_response_models_expand_generics_arrays_inheritance_and_cycles(self):
        self.write("smali/Api.smali", '''
            .class public interface abstract La/Api;
            .super Ljava/lang/Object;
            .method public abstract get()Lretrofit2/Call;
              .annotation system Ldalvik/annotation/Signature;
                value = {"()Lretrofit2/Call<", "La/Root;", ">;"}
              .end annotation
              .annotation runtime Lretrofit2/http/GET;
                value = "root"
              .end annotation
            .end method
        ''')
        self.write("smali_classes2/Root.smali", '''
            .class public La/Root;
            .super La/Base;
            .annotation runtime Lkotlin/Metadata;
                k = 0x1
            .end annotation
            .field public children:Ljava/util/List;
              .annotation system Ldalvik/annotation/Signature;
                value = {"Ljava/util/List<", "La/Child;", ">;"}
              .end annotation
            .end field
            .field public rows:[La/Child;
            .field public archived:Z
              .annotation runtime Lcom/squareup/moshi/Json;
                name = "is_archived"
              .end annotation
            .end field
            .field public count:I
            .field public transient cached:La/NotOnWire;
            .field public static INSTANCE:La/Root;
        ''')
        self.write("smali/Child.smali", '''
            .class public La/Child;
            .super Ljava/lang/Object;
            .field public owner:La/Root;
            .field private title:Ljava/lang/String;
              .annotation runtime Lcom/google/gson/annotations/SerializedName;
                value = "headline"
                alternate = {"caption", "name"}
              .end annotation
            .end field
        ''')
        self.write("smali/Base.smali", ".class La/Base;\n.super Ljava/lang/Object;\n.field public id:J\n")
        result = self.run_harvest()
        models = {m["class_descriptor"]: m for m in result["models"]}
        self.assertEqual(set(models), {"La/Root;", "La/Child;", "La/Base;"})
        root = {f["name"]: f for f in models["La/Root;"]["fields"]}
        self.assertEqual(root["archived"]["serialized_name"], "is_archived")
        self.assertEqual(root["count"]["serialized_name"], "count")
        self.assertIsNone(root["count"]["nullable"])
        self.assertIsNone(root["archived"]["required"])
        self.assertNotIn("INSTANCE", root)
        child = {f["name"]: f for f in models["La/Child;"]["fields"]}
        self.assertEqual(child["title"]["serialized_name"], "headline")
        self.assertEqual(child["title"]["aliases"], ["caption", "name"])
        self.assertIn("kotlin_semantics_unknown", {d["code"] for d in result["diagnostics"]})

    def test_annotation_ownership_and_nested_subannotations(self):
        self.write("smali/boundaries.smali", '''
            .class public Lb/Scope;
            .super Ljava/lang/Object;
            .annotation runtime Lretrofit2/http/GET;
              value = "class-is-not-endpoint"
            .end annotation
            .field public ignored:I
              .annotation runtime Lretrofit2/http/POST;
                value = "field-is-not-endpoint"
              .end annotation
            .end field
            .method public abstract actual(Ljava/lang/String;)V
              .param p1
                .annotation runtime Lcustom/Nested;
                  nested = .subannotation Lcustom/Value;
                    value = "not-a-retrofit-path"
                  .end subannotation
                .end annotation
                .annotation runtime Lretrofit2/http/Query;
                  value = "q#quoted"
                .end annotation
              .end param
              .annotation runtime Lretrofit2/http/GET;
                value = "real#fragment"
              .end annotation
            .end method
        ''')
        result = self.run_harvest()
        self.assertEqual(len(result["endpoints"]), 1)
        endpoint = result["endpoints"][0]
        self.assertEqual(endpoint["http"]["path"], "real#fragment")
        self.assertEqual(endpoint["parameters"][0]["name"], "q#quoted")
        self.assertEqual(len(endpoint["parameters"][0]["annotations"]), 2)
        self.assertEqual(len(endpoint["annotations"]), 1)
        self.assertIn(".subannotation", "\n".join(endpoint["parameters"][0]["annotations"][0]["raw_lines"]))

    def test_unknown_annotations_and_encoding_are_preserved_not_guessed(self):
        self.write("smali/unknown.smali", r'''
            .class public Lunknown/Service;
            .super Ljava/lang/Object;
            .method public abstract x(Ljava/lang/String;)V
              .param p1
                .annotation runtime Lretrofit2/http/Query;
                  value = "name"
                  encoded = .enum Lunknown/Encoding;->MAGIC:Lunknown/Encoding;
                .end annotation
              .end param
              .annotation runtime Lretrofit2/http/CustomEncoding;
                value = "ciphertext"
              .end annotation
              .annotation runtime Lretrofit2/http/GET;
                value = "bad/\q"
              .end annotation
            .end method
        ''')
        result = self.run_harvest()
        endpoint = result["endpoints"][0]
        self.assertIsNone(endpoint["http"]["path"])
        self.assertIsNone(endpoint["parameters"][0]["encoded"])
        codes = {d["code"] for d in result["diagnostics"]}
        self.assertTrue({"unknown_http_annotation", "unknown_encoding", "unknown_string_encoding", "unknown_http_path"} <= codes)
        unknown = next(d for d in result["diagnostics"] if d["code"] == "unknown_http_annotation")
        self.assertIn("ciphertext", unknown["raw"])

    def test_unterminated_annotation_does_not_eat_next_method(self):
        self.write("smali/broken.smali", '''
            .class public Lbroken/Service;
            .super Ljava/lang/Object;
            .method public abstract first()V
              .annotation runtime Lretrofit2/http/GET;
                value = "first"
            .end method
            .method public abstract second()V
              .annotation runtime Lretrofit2/http/POST;
                value = "second"
              .end annotation
            .end method
        ''')
        result = self.run_harvest()
        self.assertEqual({e["http"]["path"] for e in result["endpoints"]}, {"first", "second"})
        self.assertIn("unterminated_annotation", {d["code"] for d in result["diagnostics"]})
        self.assertFalse(result["endpoints"][0]["annotations"][0]["terminated"])

    def test_multipart_headers_and_map_parameter_metadata(self):
        self.write("smali/maps.smali", '''
            .class public Lmap/Service;
            .super Ljava/lang/Object;
            .method public abstract send(Ljava/util/Map;Ljava/util/Map;Lokhttp3/MultipartBody$Part;)V
              .param p1
                .annotation runtime Lretrofit2/http/QueryMap;
                  encoded = false
                .end annotation
              .end param
              .param p2
                .annotation runtime Lretrofit2/http/HeaderMap;
                .end annotation
              .end param
              .param p3
                .annotation runtime Lretrofit2/http/Part;
                .end annotation
              .end param
              .annotation runtime Lretrofit2/http/Multipart;
              .end annotation
              .annotation runtime Lretrofit2/http/Headers;
                value = {"X-Mode: candidate"}
              .end annotation
              .annotation runtime Lretrofit2/http/POST;
                value = "parts"
              .end annotation
            .end method
        ''')
        endpoint = self.run_harvest()["endpoints"][0]
        self.assertEqual(endpoint["media_types"], ["multipart/form-data"])
        self.assertEqual([p["location"] for p in endpoint["parameters"]], ["query", "header", "part"])
        self.assertIsNone(endpoint["parameters"][0]["name"])
        self.assertFalse(endpoint["parameters"][0]["encoded"])

    def test_source_binding_and_unresolved_models_are_explicit(self):
        self.write("smali/missing.smali", '''
            .class public Lmissing/Service;
            .super Ljava/lang/Object;
            .method public abstract read()Lmissing/DTO;
              .annotation runtime Lretrofit2/http/GET;
                value = "x"
              .end annotation
            .end method
        ''')
        result = self.run_harvest()
        self.assertEqual(result["models"], [])
        self.assertEqual(result["coverage"]["unresolved_model_descriptors"], ["Lmissing/DTO;"])
        self.assertIn("unresolved_model", {d["code"] for d in result["diagnostics"]})
        self.assertFalse(result["coverage"]["network_requests_performed"])


if __name__ == "__main__":
    unittest.main()
