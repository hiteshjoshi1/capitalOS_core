import { useEffect, useMemo, useState } from "react";

import PageShell from "../components/PageShell";
import "../App.css";
import {
  api,
  type RagAuthorLibrary,
  type RagLibraryAuthor,
  type RagLibraryDocumentDetail,
  type RagLibraryDocumentSummary,
  type RagLibraryRelatedDocument,
} from "../lib/api";

function prettyFieldName(field: string | null | undefined): string {
  if (!field) return "Documents";
  return field
    .split(/[_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function documentMetaEntries(document: RagLibraryDocumentSummary | RagLibraryDocumentDetail): Array<[string, string]> {
  const entries: Array<[string, string | null | undefined]> = [
    ["Author", document.author_name ?? document.author_id],
    ["Date", document.publication_label],
    ["Venue", document.venue],
    ["Collection", document.collection],
    ["Canonical", document.canonical_status],
    ["Source type", document.source_type],
    ["Work type", document.work_type],
  ];
  return entries.filter(([, value]) => Boolean(value)) as Array<[string, string]>;
}

function renderRelatedDocuments(
  label: string,
  documents: RagLibraryRelatedDocument[],
  onOpenDocument: (documentId: string) => void,
) {
  if (!documents.length) return null;
  return (
    <div className="authorLibraryRelatedGroup">
      <div className="cardTitle">{label}</div>
      <div className="authorLibraryRelatedList">
        {documents.map((document) => (
          <button
            key={document.id}
            className="authorLibraryRelatedButton"
            type="button"
            onClick={() => onOpenDocument(document.id)}
          >
            <span className="authorLibraryRelatedTitle">{document.title}</span>
            <span className="muted">
              {[
                document.author_name,
                document.publication_label,
                document.work_type,
              ]
                .filter(Boolean)
                .join(" • ") || "Open related document"}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function DocumentCard({
  document,
  selected,
  onOpen,
}: {
  document: RagLibraryDocumentSummary;
  selected: boolean;
  onOpen: (documentId: string) => void;
}) {
  return (
    <button
      type="button"
      className={`authorLibraryDocumentCard${selected ? " authorLibraryDocumentCardActive" : ""}`}
      onClick={() => onOpen(document.id)}
    >
      <div className="authorLibraryDocumentHeader">
        <div>
          <div className="authorLibraryDocumentTitle">{document.title}</div>
          <div className="muted">
            {document.author_name ?? document.author_id ?? "Unknown author"}
          </div>
        </div>
        <span className="pill">{document.char_count.toLocaleString()} chars</span>
      </div>
      <div className="authorLibraryMetaGrid">
        {documentMetaEntries(document).map(([label, value]) => (
          <span key={`${document.id}-${label}`} className="authorLibraryMetaChip">
            <strong>{label}:</strong> {value}
          </span>
        ))}
      </div>
      <div className="authorLibraryMetaGrid">
        {document.parent_title ? (
          <span className="authorLibraryMetaChip">
            <strong>Parent:</strong> {document.parent_title}
          </span>
        ) : null}
        {document.child_count > 0 ? (
          <span className="authorLibraryMetaChip">
            <strong>Related:</strong> {document.child_count} linked
          </span>
        ) : null}
      </div>
      {document.source_url ? (
        <span className="authorLibraryMetaChip">
          <strong>Source:</strong> {document.source_url}
        </span>
      ) : null}
    </button>
  );
}

export default function AuthorLibrary() {
  const [authors, setAuthors] = useState<RagLibraryAuthor[]>([]);
  const [authorsLoading, setAuthorsLoading] = useState(true);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [selectedAuthorId, setSelectedAuthorId] = useState("");
  const [selectedDocumentId, setSelectedDocumentId] = useState("");
  const [library, setLibrary] = useState<RagAuthorLibrary | null>(null);
  const [documentDetail, setDocumentDetail] = useState<RagLibraryDocumentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const loadAuthors = async () => {
      try {
        setError(null);
        const data = await api.ragLibraryAuthors();
        if (cancelled) return;
        setAuthors(data);
        setSelectedAuthorId((currentAuthorId) => currentAuthorId || data[0]?.id || "");
      } catch (err: unknown) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setAuthorsLoading(false);
      }
    };
    void loadAuthors();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedAuthorId) return;
    let cancelled = false;
    const loadLibrary = async () => {
      setLibraryLoading(true);
      try {
        setError(null);
        const data = await api.ragAuthorLibrary(selectedAuthorId);
        if (cancelled) return;
        setLibrary(data);
        setSelectedDocumentId((previousDocumentId) =>
          data.documents.some((document) => document.id === previousDocumentId)
            ? previousDocumentId
            : (data.documents[0]?.id ?? ""),
        );
      } catch (err: unknown) {
        if (cancelled) return;
        setLibrary(null);
        setSelectedDocumentId("");
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLibraryLoading(false);
      }
    };
    void loadLibrary();
    return () => {
      cancelled = true;
    };
  }, [selectedAuthorId]);

  useEffect(() => {
    if (!selectedDocumentId) return;
    let cancelled = false;
    const loadDocument = async () => {
      setDetailLoading(true);
      try {
        setError(null);
        const data = await api.ragLibraryDocument(selectedDocumentId);
        if (!cancelled) setDocumentDetail(data);
      } catch (err: unknown) {
        if (cancelled) return;
        setDocumentDetail(null);
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    };
    void loadDocument();
    return () => {
      cancelled = true;
    };
  }, [selectedDocumentId]);

  const groupedSections = useMemo(() => library?.groups ?? [], [library]);

  return (
    <PageShell
      title="Author Library"
      subtitle="Browse each author’s corpus as readable documents instead of one raw ingestion blob."
      headerActions={(
        <label className="pill">
          <span>Author</span>
          <select
            aria-label="Choose author corpus"
            className="monthInput"
            disabled={!authors.length}
            value={selectedAuthorId}
            onChange={(event) => setSelectedAuthorId(event.target.value)}
          >
            {!authors.length ? <option value="">No corpus yet</option> : null}
            {authors.map((author) => (
              <option key={author.id} value={author.id}>
                {author.name}
              </option>
            ))}
          </select>
        </label>
      )}
    >
      <div className="dashboardWrap">
        {authorsLoading || libraryLoading ? (
          <div className="card">
            <div className="cardTitle">Loading author library</div>
            <div className="muted">Fetching corpus metadata and logical documents…</div>
          </div>
        ) : null}

        {error ? (
          <div className="card error">
            <div className="cardTitle">Unable to load author library</div>
            <pre className="pre">{error}</pre>
          </div>
        ) : null}

        {!authorsLoading && !authors.length && !error ? (
          <div className="card">
            <div className="cardTitle">No author corpus available yet</div>
            <div className="muted">
              Ingested logical documents will appear here once an author corpus has been loaded into CapitalOS.
            </div>
          </div>
        ) : null}

        {library ? (
          <>
            <section className="grid authorLibraryOverview">
              <div className="card">
                <div className="cardTitle">Corpus overview</div>
                <h2>{library.author.name}</h2>
                <div className="authorLibraryMetaGrid">
                  <span className="authorLibraryMetaChip">
                    <strong>Documents:</strong> {library.author.document_count}
                  </span>
                  <span className="authorLibraryMetaChip">
                    <strong>Sources:</strong> {library.author.source_count}
                  </span>
                  {library.grouping.primary_field ? (
                    <span className="authorLibraryMetaChip">
                      <strong>Grouped by:</strong> {prettyFieldName(library.grouping.primary_field)}
                    </span>
                  ) : null}
                  {library.grouping.secondary_field ? (
                    <span className="authorLibraryMetaChip">
                      <strong>Secondary:</strong> {prettyFieldName(library.grouping.secondary_field)}
                    </span>
                  ) : null}
                </div>
                <div className="authorLibraryMetaGrid">
                  {library.author.collections.map((collection) => (
                    <span key={collection} className="authorLibraryMetaChip">
                      <strong>Collection:</strong> {collection}
                    </span>
                  ))}
                  {library.author.work_types.map((workType) => (
                    <span key={workType} className="authorLibraryMetaChip">
                      <strong>Work type:</strong> {workType}
                    </span>
                  ))}
                  <span className="authorLibraryMetaChip">
                    <strong>Updated:</strong> {formatDateTime(library.author.latest_document_at)}
                  </span>
                </div>
              </div>
            </section>

            <section className="grid authorLibraryLayout">
              <div className="card authorLibraryListPanel">
                <div className="cardTitle">Logical documents</div>
                {groupedSections.length ? (
                  <div className="authorLibraryGroupStack">
                    {groupedSections.map((group) => (
                      <section key={`${group.field}:${group.value}`} className="authorLibraryGroup">
                        <div className="authorLibraryGroupHeader">
                          <h3>{group.label}</h3>
                          <span className="pill">
                            {prettyFieldName(group.field)} • {group.document_count}
                          </span>
                        </div>
                        {group.secondary_groups.length ? (
                          <div className="authorLibrarySecondaryStack">
                            {group.secondary_groups.map((secondaryGroup) => (
                              <div key={`${group.value}:${secondaryGroup.value}`} className="authorLibrarySecondaryGroup">
                                <div className="cardTitle">
                                  {prettyFieldName(secondaryGroup.field)}: {secondaryGroup.label}
                                </div>
                                <div className="authorLibraryDocumentStack">
                                  {secondaryGroup.documents.map((document) => (
                                    <DocumentCard
                                      key={document.id}
                                      document={document}
                                      selected={selectedDocumentId === document.id}
                                      onOpen={setSelectedDocumentId}
                                    />
                                  ))}
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="authorLibraryDocumentStack">
                            {group.documents.map((document) => (
                              <DocumentCard
                                key={document.id}
                                document={document}
                                selected={selectedDocumentId === document.id}
                                onOpen={setSelectedDocumentId}
                              />
                            ))}
                          </div>
                        )}
                      </section>
                    ))}
                  </div>
                ) : (
                  <div className="authorLibraryDocumentStack">
                    {library.documents.map((document) => (
                      <DocumentCard
                        key={document.id}
                        document={document}
                        selected={selectedDocumentId === document.id}
                        onOpen={setSelectedDocumentId}
                      />
                    ))}
                  </div>
                )}
              </div>

              <div className="card authorLibraryReaderPanel">
                <div className="cardTitle">Reader</div>
                {detailLoading ? (
                  <div className="muted">Loading logical document…</div>
                ) : documentDetail ? (
                  <div className="authorLibraryReaderContent">
                    <div className="authorLibraryReaderHeader">
                      <div>
                        <h2>{documentDetail.title}</h2>
                        <div className="muted">
                          {documentDetail.author_name ?? documentDetail.author_id ?? "Unknown author"}
                        </div>
                      </div>
                      <span className="pill">{documentDetail.char_count.toLocaleString()} chars</span>
                    </div>

                    <div className="authorLibraryMetaGrid">
                      {documentMetaEntries(documentDetail).map(([label, value]) => (
                        <span key={`${documentDetail.id}-${label}`} className="authorLibraryMetaChip">
                          <strong>{label}:</strong> {value}
                        </span>
                      ))}
                      {documentDetail.source_author_name ? (
                        <span className="authorLibraryMetaChip">
                          <strong>Source provenance:</strong> {documentDetail.source_author_name}
                        </span>
                      ) : null}
                    </div>

                    {documentDetail.source_url ? (
                      <a className="authorLibrarySourceLink" href={documentDetail.source_url} rel="noreferrer" target="_blank">
                        Open provenance link
                      </a>
                    ) : null}

                    {renderRelatedDocuments(
                      "Parent document",
                      documentDetail.parent_document ? [documentDetail.parent_document] : [],
                      setSelectedDocumentId,
                    )}
                    {renderRelatedDocuments("Related documents", documentDetail.child_documents, setSelectedDocumentId)}

                    <div className="authorLibraryReaderText" data-testid="author-library-reader-text">
                      {documentDetail.clean_text}
                    </div>
                  </div>
                ) : (
                  <div className="muted">Choose a logical document to read it here.</div>
                )}
              </div>
            </section>
          </>
        ) : null}
      </div>
    </PageShell>
  );
}
