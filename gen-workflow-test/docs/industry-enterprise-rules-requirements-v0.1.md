# GEO Industry Standards and Enterprise Rules Requirements

Version: v0.1  
Status: First draft  
Project: `gen-workflow-test`

## 1. Objective

Extend the existing workflow from client materials and enterprise rules to a complete industry-aware content-quality workflow.

```text
Industry materials + sales scenario + client materials
        ↓
Industry standard + enterprise rules
        ↓
Article quality standard
        ↓
Dify workflow + batch evaluation
```

The system evaluates client-rule compliance, industry-boundary compliance, professional content quality, evidence quality, and user decision value.

## 2. Scope

### Included in v0.1

1. Sales completes a scenario form.
2. Sales uploads client writing requirements and supporting materials.
3. The system selects an active industry standard.
4. The model extracts enterprise rules.
5. The model generates an article quality standard for the current task.
6. The effective rules are injected into the existing YAML template.
7. A client-specific Dify workflow is exported.
8. Generated articles are evaluated using the same effective standard.
9. Rule versions and batch snapshots are retained.

### Excluded in v0.1

- Automatically making legal conclusions.
- Rebuilding the formal industry standard for every sales request.
- Covering an entire industry in one release.
- Replacing expert, legal, or client approval.
- Changing the existing Dify node topology.
- Automatically crawling all industry materials.

## 3. Core concepts

### Industry standard

A reusable professional baseline for a specific industry scenario. It is built from regulatory materials, professional guidance, typical cases, expert review, and user problems.

It defines risky or misleading claims, concepts users must understand, evidence requirements, and minimum requirements for professional, complete, and trustworthy content.

It is built, reviewed, versioned, and reused. Sales selects an active version; sales does not directly rewrite it.

### Enterprise rules

Rules extracted from one client’s materials. They define brand and product names, preferred messages, prohibited expressions, business boundaries, and approved facts.

Enterprise rules are client-specific and must not be promoted to industry standards.

### Article quality standard

The effective standard for one article task:

```text
Applicable industry requirements
+ applicable enterprise rules
+ current article task requirements
```

It is used by outline planning, generation, review, and batch evaluation.

## 4. Pilot scenario

The first validation should use one narrow scenario:

```text
Industry: education and training
Audience: parents of primary-school students
Purpose: compare and select a course
Content type: course introduction / course-selection guide
Decision stage: before comparison and enrollment
```

This is a pilot scenario, not a complete education-industry standard.

## 5. Roles

### Sales

Sales provides the business scenario and real user problems. Sales does not define the industry standard.

### Industry-standard owner

Collects sources, organizes model extraction, checks applicability, resolves conflicts, and publishes active versions.

### Client

Confirms enterprise facts, brand rules, business boundaries, and whether the article quality standard fits the business objective.

### Expert or legal reviewer

Reviews hard boundaries, evidence requirements, risk disclosures, and exceptions for high-risk industries.

## 6. Sales scenario form

The form captures scenario context. It does not ask sales to write the industry standard.

### Basic fields

| Field | Required | Description |
|---|---:|---|
| Client name | Yes | Links the request to a client |
| Client slug | Yes | Reuses the existing project identifier |
| Industry | Yes | Medical, education, finance, etc. |
| Sub-industry | Yes | Example: primary-school education |
| Topic | Yes | Current article topic or keyword direction |
| Content type | Yes | Guide, product introduction, comparison, case, etc. |
| Content purpose | Yes | Awareness, comparison, selection, conversion, risk education |
| Target audience | Yes | Primary reader and role |
| Decision stage | Yes | Learning, comparison, verification, selection, post-use evaluation |

### Seven scenario fields

1. **Applicable scenario**: industry, audience, purpose, content type, and decision stage.
2. **User decision**: what the user needs to decide and what mistakes are likely.
3. **Professional judgment dimensions**: what professionals normally examine.
4. **Must explain**: concepts, conditions, boundaries, and distinctions users need.
5. **Must avoid**: known risky claims, overstrong wording, and misleading patterns.
6. **Evidence requirements**: known sources, data, qualifications, cases, or proof.
7. **Quality goals**: desired completeness, professionalism, trust, and decision value.

These fields are scenario inputs. They do not become formal industry requirements without source support and review.

## 7. Client materials

Supported materials include writing guidelines, historical article feedback, review comments, brand and product materials, enterprise facts, approved and prohibited expressions, data, cases, qualifications, and official evidence.

The model must distinguish:

```text
Writing requirements → enterprise rules
Enterprise facts → client knowledge materials
Industry claims → not accepted as industry standards without external support
```

## 8. Industry-standard sources

The formal industry standard should be based on laws and regulatory documents, industry and professional standards, professional guidance and expert consensus, enforcement and complaint cases, user questions and misconceptions, and high-quality content examples.

If no active standard exists for a selected scenario, the system must show that fact, allow creation of a draft, and require review before formal workflow use.

## 9. Model processing

### Enterprise-rule extraction

Input: client materials. Output: an enterprise-rule draft using the existing categories: `identity`, `fact`, `prohibition`, `stance`, `scope`, `voice`, `structure`, `citation`, and `delivery`.

### Industry-standard activation

Select applicable requirements from the active industry standard using industry, audience, content purpose, content type, decision stage, and article topic. The original standard is not modified.

### Article-quality generation

Input:

```text
active industry standard
+ sales scenario form
+ enterprise-rule draft
+ client evidence materials
```

Output:

```yaml
quality_standard:
  scenario: current article scenario
  audience: target audience
  purpose: content purpose
  must_explain: required explanations
  must_prove: claims and evidence requirements
  must_avoid: prohibited claims and misleading patterns
  outline_requirements: required outline coverage
  generation_requirements: writing requirements
  evaluation_requirements: post-generation checks
  human_review_items: items requiring manual review
  source_trace: source for each requirement
  conflicts: unresolved conflicts
```

The model must not invent legal conclusions, turn client preferences into industry rules, promote sales experience into professional standards, ignore applicability conditions, or silently resolve conflicts.

## 10. Rule-combination principles

```text
Industry standard: professional and risk baseline
Enterprise rules: client-specific expression and business boundary
Article quality standard: final requirements for this article
```

Hard industry boundaries normally take priority over general client preferences. Conflicts must show both rules, both sources, applicable conditions, proposed handling, and whether manual confirmation is required.

## 11. YAML integration

Version 0.1 preserves the existing workflow topology and supports three context slots:

```text
industry_standard
enterprise_rules
article_quality_standard
```

| Context | Main use |
|---|---|
| Industry professional judgment | Scenario analysis and outline |
| Industry hard boundaries | Outline, generation, and review |
| Enterprise brand and business rules | Analysis, outline, generation, and review |
| Article quality standard | Outline, generation, review, and evaluation |
| Terms, replacements, and regex | Deterministic gate |
| Evaluation requirements | Project evaluator and batch report |

Full regulatory text should not be injected into every node. The workflow should receive a filtered, structured, scenario-specific standard.

## 12. Batch evaluation

The batch report should separate:

```text
Enterprise-rule compliance
Industry hard-boundary compliance
Industry professional quality
Evidence completeness
User decision value
Manual-review items
```

Every industry requirement should retain its rule ID, source, applicable scenario, verdict, article evidence, revision suggestion, and enforcement method.

The existing `rules_snapshot.yaml` should also record:

```yaml
resolved_from:
  industry_standard:
    id: education-course-choice
    version: 0.1.0
  enterprise_rules:
    client_id: example
    version: 0.1.0
  article_quality_standard:
    version: 0.1.0
```

## 13. User flow

```text
Sales completes scenario form
    ↓
Sales uploads client materials
    ↓
System selects active industry standard
    ↓
Model extracts enterprise rules
    ↓
Model generates article quality standard
    ↓
Human confirms rules and conflicts
    ↓
System injects the effective standard into YAML
    ↓
System exports client Dify workflow
```

## 14. Acceptance criteria

The pilot is accepted when one real client and one real scenario can complete the entire loop:

- industry standard, enterprise rules, and article quality standard are clearly separated;
- the industry standard can be reused by multiple clients;
- client rules do not modify the industry standard;
- the effective standard guides outline planning and generation;
- the existing workflow topology remains valid;
- industry and enterprise results are reported separately;
- evidence gaps can be marked as unclear or manual review;
- the batch records all versions used at evaluation time.

The pilot must test incorrect client expression, industry-boundary violation, missing industry-required content, and important claims without sufficient evidence.

## 15. Recommended implementation order

1. Select one industry, one audience, and one content purpose.
2. Prepare a reviewed pilot industry standard.
3. Extract enterprise rules for one real client.
4. Generate the article quality standard.
5. Modify the master YAML to accept the three context slots.
6. Generate and run one client workflow in Dify.
7. Import articles and verify layered batch evaluation.
8. Build the front-end workflow after the closed loop is stable.

First milestone:

```text
Industry sources
→ industry standard
→ enterprise rules
→ article quality standard
→ YAML workflow
→ article evaluation
→ feedback and versioned revision
```
