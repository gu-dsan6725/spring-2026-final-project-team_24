# Data Entities

A **data entity** is a dataset reference that participates in the knowledge graph alongside content concepts. It stores download metadata so group members can retrieve the dataset, a free-text description of provenance, and an appendable log of freeform status entries (ML evaluations, pipeline results, annotations, etc.).

## Document Shape

Stored as a single MongoDB document in the `data_entities` collection:

```json
{
  "_id": "de_abc123",
  "owner_id": "user_42",
  "name": "MNIST Test Set",
  "description": "10K handwritten digit images from the MNIST test split, used for classifier benchmarking.",

  "source": {
    "storage": "s3",
    "bucket": "dsan-datasets",
    "key": "datasets/mnist_test.csv",
    "url": "https://dsan-datasets.s3.amazonaws.com/datasets/mnist_test.csv",
    "format": "csv",
    "size_bytes": 18274930,
    "checksum_sha256": "a1b2c3..."
  },

  "entries": [
    {
      "id": "ent_001",
      "created_at": "2026-04-08T14:30:00Z",
      "created_by": "user_42",
      "note": "Baseline random forest, default hyperparams",
      "data": {
        "accuracy": 0.973,
        "f1_macro": 0.971,
        "model": "RandomForest",
        "n_estimators": 100
      }
    },
    {
      "id": "ent_002",
      "created_at": "2026-04-09T09:15:00Z",
      "created_by": "user_55",
      "note": "XGBoost with tuned LR, improved across all metrics",
      "data": {
        "accuracy": 0.981,
        "roc_auc": 0.995,
        "pipeline": "custom_eval_v2",
        "config": {"learning_rate": 0.01, "max_depth": 6}
      }
    }
  ],

  "tags": ["classification", "mnist", "benchmark"],
  "created_at": "2026-04-07T...",
  "updated_at": "2026-04-09T..."
}
```

## Fields

### Top-level

| Field | Type | Description |
|---|---|---|
| `_id` | string | Unique identifier |
| `owner_id` | string | User who created the entity |
| `name` | string | Human-readable dataset name |
| `description` | string (optional) | Free-text note about provenance, collection method, caveats |
| `source` | object | Download metadata (see below) |
| `entries` | array | Appendable log of freeform status entries |
| `tags` | string[] | For discovery and filtering across the graph |
| `created_at` | datetime | Entity creation timestamp |
| `updated_at` | datetime | Last modification timestamp |

### Source

Everything a member needs to download the dataset:

| Field | Type | Description |
|---|---|---|
| `storage` | string | Platform type: `"s3"`, `"gcs"`, `"azure"`, `"url"` |
| `url` | string | Direct download link |
| `bucket` | string (optional) | Cloud storage bucket name |
| `key` | string (optional) | Object key / file path within the bucket |
| `format` | string (optional) | File format: `"csv"`, `"parquet"`, `"json"`, `"xlsx"`, etc. |
| `size_bytes` | int (optional) | File size for UI display and download estimates |
| `checksum_sha256` | string (optional) | Integrity verification hash |

### Entry

Each entry is an append-only freeform JSON record:

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique entry identifier (generated server-side) |
| `created_at` | datetime | When the entry was appended |
| `created_by` | string | User who appended it |
| `note` | string (optional) | Free-text description of what this entry represents |
| `data` | object | Arbitrary JSON blob — ML metrics, pipeline configs, status updates, whatever the user defines |

No enforced schema on `data`. Users can log accuracy metrics, confusion matrices, hyperparameter configs, data quality reports, or any structured result from their custom pipelines.

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/data-entities` | Create a new data entity with source info and description |
| `GET` | `/data-entities/{id}` | Full document including all entries |
| `POST` | `/data-entities/{id}/entries` | Append a new freeform entry (MongoDB `$push`) |
| `GET` | `/data-entities/{id}/entries` | List entries only (optional date range filter) |
| `DELETE` | `/data-entities/{id}/entries/{entry_id}` | Remove a specific entry (owner/admin only) |

## Pydantic Schemas

```python
class SourceInfo(BaseModel):
    storage: str                          # "s3", "gcs", "azure", "url"
    url: str                              # direct download link
    bucket: str | None = None
    key: str | None = None
    format: str | None = None
    size_bytes: int | None = None
    checksum_sha256: str | None = None

class EntryAppend(BaseModel):
    note: str | None = None
    data: dict[str, Any]                  # arbitrary JSON blob

class DataEntityCreate(BaseModel):
    name: str
    description: str | None = None
    source: SourceInfo
    tags: list[str] = []

class EntryRead(BaseModel):
    id: str
    created_at: datetime
    created_by: str
    note: str | None
    data: dict[str, Any]

class DataEntityRead(BaseModel):
    id: str
    owner_id: str
    name: str
    description: str | None
    source: SourceInfo
    entries: list[EntryRead]
    tags: list[str]
    created_at: datetime
    updated_at: datetime
```

## Design Rationale

- **Single document** — with expected entry count under 50, the document stays well within MongoDB's 16MB limit. Simpler than a two-collection join.
- **Append-only entries** — `$push` is atomic in MongoDB, safe for concurrent appends. Past entries are never modified (audit trail).
- **Freeform `data`** — maximum flexibility. Users define their own evaluation schemas rather than conforming to a fixed structure.
- **Source as download reference** — the data entity doesn't store the dataset itself; it points to where it lives (S3, GCS, a URL). Members use the source metadata to download it.

## Data Entity as Specialized Dive

A data entity is conceptually a **specialized dive** — see [Edges — Dive Hyperedges](02-edges.md#experimental--deferred-dive-hyperedges). Where a generic dive spans multiple foundation concepts and provides advanced exploration territory, a data entity does the same with a concrete dataset at its center:

| Dive concept | Data entity equivalent |
|---|---|
| Foundation concepts | Base methodology concepts + data pipeline steps (directed edges) |
| Dive content | The dataset itself (source metadata + description) |
| Perspectives | Entries from different members — each with their own methodology, pipeline config, and evaluation metrics |

Multiple group members can independently contribute entries to the same data entity, each representing a different analytical approach (different models, hyperparameters, preprocessing pipelines). This mirrors how a dive collects multiple foundation subgraphs — here, each member's graph of methodology concepts and directed pipeline edges constitutes their "approach" to the shared dataset.

The actual dataset lives on remote storage (S3, GCS, URL) while the description and statistical entries live in the data entity document.

## Graph Participation

A data entity is a node in the knowledge graph like any concept. It can:
- Be connected to content concepts via edges (e.g., "this dataset demonstrates concept X")
- Serve as foundation for items (e.g., "given this dataset, perform analysis Y")
- Be tagged and discovered in group landscapes
- Serve as a dive point where members converge with different analytical methodologies

## Charts & Statistical Properties

User-configured chart definitions can be attached to each data entity:

- **Chart type** — bar, line, scatter, histogram, box plot, heatmap, etc.
- **Axes / dimensions** — user maps columns to visual channels
- **Statistical overlays** — mean, median, std dev, regression lines, confidence intervals
- **Filters & grouping** — slice by categorical columns

> *[Deferred]* — Chart definition schema and rendering pipeline will be designed when the frontend visualization layer is built. Edge-level data properties (correlation between datasets, transformation pipelines) also deferred.
