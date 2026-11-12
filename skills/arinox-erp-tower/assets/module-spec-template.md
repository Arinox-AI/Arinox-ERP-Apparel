# <Module Name> — module spec

| | |
|---|---|
| Slug | `<slug>` |
| Status | draft / approved / live / retired |
| Approved by / on | <person> / <yyyy-mm-dd> |
| Builder agent | ERP agent / coding agent |
| Scripts run on | erp |

## 1. Workflow
<One paragraph: who does what, on which document, in what order.>

## 2. Reused, not rebuilt
| Existing record | How this module uses it |
|---|---|
| Sales Order | link field `sales_order` |

## 3. DocTypes
### <Module> <Thing>  (submittable: yes/no · naming: `<SLUG>-.YYYY.-.####`)
| fieldname | label | type | options | reqd | in list |
|---|---|---|---|---|---|
| sales_order | Sales Order | Link | Sales Order | 1 | 1 |

Permissions: | role | read | write | create | submit | cancel | delete |

## 4. Custom fields on existing doctypes
| doctype | fieldname (`custom_<slug>_…`) | type | insert_after | why |

## 5. Server Scripts (all created disabled, enabled one by one)
| name (`<slug>_…`) | type | doctype + event / api_method / frequency | does | throws when |

## 6. Client Scripts · Reports · Print Formats · Notifications · Workflow · Workspace
| kind | name | one line |

## 7. Test plan
| # | rule | input (ZZTEST rows) | expected |

## 8. Rollback list (reverse creation order)
| doctype | name |

## 9. Tower registration
```json
{"module": "<Module Name>", "slug": "<slug>", "doctypes": {}, "api_methods": [], "scripts_run_on": "erp", "spec": "erp-modules/<slug>/SPEC.md"}
```
