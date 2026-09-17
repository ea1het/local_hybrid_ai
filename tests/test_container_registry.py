# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Contract tests for package-owned registry identity and discovery."""
from __future__ import annotations
import json,unittest
from unittest import mock
from commands.upgrade import registry as container_registry
PATCH="commands.upgrade.registry"
class ContainerRegistryTests(unittest.TestCase):
 def test_parse_reference_uses_docker_hub_for_unqualified_images(self):
  ref=container_registry.parse_reference("rabbitmq:3-alpine");self.assertEqual((ref.registry,ref.registry_host,ref.repository,ref.tag,ref.digest),("docker.io","registry-1.docker.io","library/rabbitmq","3-alpine",None))
 def test_parse_reference_preserves_ghcr_package_and_digest(self):
  ref=container_registry.parse_reference("ghcr.io/firecrawl/firecrawl@sha256:1910ef");self.assertEqual(ref.registry,"ghcr.io");self.assertEqual(ref.repository,"firecrawl/firecrawl");self.assertIsNone(ref.tag);self.assertEqual(ref.digest,"sha256:1910ef")
 def test_repo_digest_matches_tagged_image_repository(self):self.assertEqual(container_registry._repo_digest_for_image("rabbitmq:3-alpine",["rabbitmq@sha256:abc","redis@sha256:def"]),"sha256:abc")
 def test_repo_digest_matches_docker_hub_library_form(self):self.assertEqual(container_registry._repo_digest_for_image("rabbitmq:3-alpine",["docker.io/library/rabbitmq@sha256:abc"]),"sha256:abc")
 def test_repo_digest_matches_explicit_docker_io_namespace(self):self.assertEqual(container_registry._repo_digest_for_image("docker.io/searxng/searxng:2026.9.5-c7f3080aa",["searxng/searxng@sha256:55e1fa15"]),"sha256:55e1fa15")
 def test_repository_name_normalizes_docker_hub_aliases(self):
  self.assertEqual(container_registry._repository_name("rabbitmq:3-alpine"),"library/rabbitmq");self.assertEqual(container_registry._repository_name("docker.io/library/rabbitmq:3-alpine"),"library/rabbitmq");self.assertEqual(container_registry._repository_name("index.docker.io/searxng/searxng:tag"),"searxng/searxng")
 def test_registry_state_prefers_human_versions_for_update_comparison(self):self.assertTrue(container_registry.RegistryState(image="x",local_digest="sha256:a",remote_digest="sha256:b",current_version="2.11.300",available_version="2.11.331").update_available)
 def test_registry_state_same_human_version_is_current(self):self.assertFalse(container_registry.RegistryState(image="x",local_digest="sha256:a",remote_digest="sha256:a",current_version="2.11.331",available_version="2.11.331").update_available)
 def test_missing_digest_is_unknown_not_update(self):self.assertIsNone(container_registry.RegistryState("rabbitmq:3-alpine",None,"sha256:b").update_available)
 def test_local_digest_follows_container_image_id(self):
  with mock.patch(PATCH+"._inspect_json",side_effect=[{"Image":"sha256:image-id"},{"RepoDigests":["docker.io/library/rabbitmq@sha256:local"]}]) as inspect_json:digest=container_registry.local_digest("firecrawl-rabbitmq","rabbitmq:3-alpine")
  self.assertEqual(digest,"sha256:local");self.assertEqual(inspect_json.call_args_list,[mock.call("firecrawl-rabbitmq"),mock.call("sha256:image-id")])
 def test_local_digest_does_not_use_container_repo_digests(self):
  with mock.patch(PATCH+"._inspect_json",side_effect=[{"Image":"sha256:image-id","RepoDigests":["rabbitmq@sha256:wrong"]},{"RepoDigests":["rabbitmq@sha256:right"]}]):self.assertEqual(container_registry.local_digest("firecrawl-rabbitmq","rabbitmq:3-alpine"),"sha256:right")
 def test_local_version_hint_accepts_oci_version_label_from_same_package(self):
  with mock.patch(PATCH+"._local_image_data",return_value={"RepoTags":[],"Config":{"Labels":{"org.opencontainers.image.version":"2.11.300"}}}):self.assertEqual(container_registry.local_version_hint("firecrawl-api","ghcr.io/firecrawl/firecrawl@sha256:old",("2.11.300","2.11.331")),"2.11.300")
 def test_registry_tags_reads_same_registry_package(self):
  body=json.dumps({"tags":["2.11.331","latest"]}).encode()
  with mock.patch(PATCH+"._registry_request",return_value=(200,{},body)) as request:probe=container_registry.registry_tags("ghcr.io/firecrawl/firecrawl@sha256:abc")
  self.assertEqual((probe.status,probe.tags),("ok",("2.11.331","latest")));self.assertEqual(request.call_args.args[0].repository,"firecrawl/firecrawl")
 def test_registry_tags_follows_registry_v2_pagination(self):
  responses=[(200,{"Link":'</v2/open-webui/open-webui/tags/list?n=1000&last=v0.1.121>; rel="next"'},json.dumps({"tags":["v0.1.121"]}).encode()),(200,{},json.dumps({"tags":["v0.11.3","v0.11.4"]}).encode())]
  with mock.patch(PATCH+"._registry_request",side_effect=responses) as request:probe=container_registry.registry_tags("ghcr.io/open-webui/open-webui:v0.11.3")
  self.assertEqual(probe.tags,("v0.1.121","v0.11.3","v0.11.4"));self.assertEqual(request.call_count,2)
 def test_registry_tags_preserves_rate_limit(self):
  with mock.patch(PATCH+"._registry_request",return_value=(429,{},b"")):probe=container_registry.registry_tags("redis:alpine")
  self.assertEqual((probe.tags,probe.status),((),"rate_limited"))
 def test_manifest_probe_returns_content_digest(self):
  with mock.patch(PATCH+"._registry_request",return_value=(200,{"Docker-Content-Digest":"sha256:remote"},b"")):probe=container_registry.manifest_probe("ghcr.io/firecrawl/firecrawl:2.11.331")
  self.assertEqual(probe,container_registry.RemoteProbe("sha256:remote","ok"))
 def test_manifest_probe_classifies_rate_limit(self):
  with mock.patch(PATCH+"._registry_request",return_value=(429,{},b"")):probe=container_registry.remote_probe("redis:alpine")
  self.assertEqual((probe.digest,probe.status),(None,"rate_limited"))
 def test_version_tags_prefer_full_plain_human_version(self):self.assertEqual(container_registry.version_tags(["latest","2","2.11","2.11.331-production","2.11.331"])[0],"2.11.331")
 def test_release_candidates_preserve_v_prefix_and_exclude_hotfix_variant(self):self.assertEqual(container_registry._release_candidates(("1.0.40-ldap-hotfix","v1.0.40","v1.0.47","v2.0.0"),"v1.0.40"),["v1.0.47","v1.0.40"])
 def test_release_candidates_exclude_older_versions_and_other_major_lines(self):self.assertEqual(container_registry._release_candidates(("v0.1.121","v0.11.3","v0.11.4","v1.0.0"),"v0.11.3"),["v0.11.4","v0.11.3"])
 def test_channel_detection_recognizes_major_minor_alpine_channel(self):self.assertTrue(container_registry._is_channel_tag("3.0-alpine",("3.0-alpine","3.0.18-alpine","3.1.2-alpine")))
 def test_major_minor_channel_does_not_fall_into_other_series(self):self.assertEqual(container_registry._channel_candidates(("2.6.10-alpine","3.0-alpine","3.0.18-alpine","3.1.2-alpine"),"3.0-alpine"),["3.0.18-alpine"])
 def test_exact_postgres_version_is_not_channel_without_more_specific_tag(self):self.assertFalse(container_registry._is_channel_tag("17.10-alpine",("17.10-alpine","17.9-alpine","18.0-alpine")))
 def test_digest_match_can_search_beyond_old_eighty_probe_limit(self):
  candidates=[f"2.11.{v}" for v in range(600,499,-1)];target=candidates[95];reference=container_registry.parse_reference("ghcr.io/firecrawl/firecrawl@sha256:old")
  with mock.patch(PATCH+".manifest_probe",side_effect=lambda ref:container_registry.RemoteProbe("sha256:old" if ref.endswith(":"+target) else "sha256:other","ok")):tag,status=container_registry._best_tag_for_digest(reference,"sha256:old",candidates)
  self.assertEqual((tag,status),(target,"ok"))
 def test_digest_only_image_maps_digest_to_human_registry_tag(self):
  image="ghcr.io/firecrawl/firecrawl@sha256:old";tags=container_registry.TagProbe(("2.11.331","2.11.300","latest"),"ok")
  def manifest(ref):return container_registry.RemoteProbe("sha256:new" if ref.endswith(":2.11.331") else ("sha256:old" if ref.endswith(":2.11.300") else None),"ok" if not ref.endswith(":latest") else "not_found")
  with mock.patch(PATCH+".local_digest",return_value="sha256:old"),mock.patch(PATCH+".local_version_hint",return_value=None),mock.patch(PATCH+".registry_tags",return_value=tags),mock.patch(PATCH+".manifest_probe",side_effect=manifest):state=container_registry.inspect("firecrawl-api",image)
  self.assertEqual((state.current_version,state.available_version),("2.11.300","2.11.331"));self.assertTrue(state.update_available)
 def test_exact_registry_tag_uses_same_family_and_major_for_available_version(self):
  tags=container_registry.TagProbe(("v0.1.121","v0.11.3","v0.11.4","v1.0.0"),"ok")
  with mock.patch(PATCH+".local_digest",return_value="sha256:old"),mock.patch(PATCH+".registry_tags",return_value=tags),mock.patch(PATCH+".manifest_probe",return_value=container_registry.RemoteProbe("sha256:new","ok")):state=container_registry.inspect("open-webui","ghcr.io/open-webui/open-webui:v0.11.3")
  self.assertEqual(state.available_version,"v0.11.4")
 def test_tracking_reference_rejects_lateral_registry_or_repository(self):
  with self.assertRaises(container_registry.RegistryError):container_registry.tracking_reference("ghcr.io/firecrawl/firecrawl@sha256:abc","docker.io/firecrawl/firecrawl:latest")
 def test_display_label_prefers_discovered_human_version(self):self.assertEqual(container_registry.display_label("ghcr.io/firecrawl/firecrawl@sha256:abc",discovered_version="2.11.300"),"2.11.300")
if __name__=="__main__":unittest.main()
