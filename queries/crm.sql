-- CRM accounts: active end-users with a website and no ZoomInfo id. Accounts with opportunities are kept on purpose
-- (the CRM label is checked for existing customers too). The industry_types column is the CRM's label.
-- Read by data_warehouse.py (read only).
SELECT
    a.crm_created_on,
    a.name,
    a.doing_business_as,
    a.company_website,
    a.industry_types,
    a.business_type,
    a.email_address,
    a.phone_number,
    a.federal_tax_id,
    a.address_composite,
    a.crm_created_by,
    a.relationship_types,
    a.status,
    a.zoominfo_id,
    a.account_key,
    a.account_id
FROM dim.Account AS a
WHERE a.zoominfo_id IS NULL
  AND a.company_website IS NOT NULL
  AND a.status = 'Active'
  AND LOWER(a.relationship_types) LIKE '%end%user%'
ORDER BY a.crm_created_on DESC;
