"use client";

import { useParams } from "next/navigation";
import useSWR from "swr";
import { TestEditor } from "@/components/test-editor";
import { Alert, Spinner } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { fetcher } from "@/lib/api";
import type { TestCase } from "@/lib/types";

export default function TestPage() {
  const { id } = useParams<{ id: string }>();
  const { project } = useWorkspace();
  const { data, error } = useSWR<TestCase>(project ? `/projects/${project.id}/test-cases/${id}` : null, fetcher, { revalidateOnFocus: false });
  if (error) return <Alert variant="error" title="Test not found">It may have been deleted, or it belongs to another project. Switch project at the top.</Alert>;
  if (!data) return <Spinner />;
  return <TestEditor key={data.id} testCase={data} />;
}
