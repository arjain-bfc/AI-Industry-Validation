-- ZoomInfo accounts: active end-users with a ZoomInfo id and a website, and no LCW opportunity term yet.
-- The industry_types column is ZoomInfo's label. Read by data_warehouse.py (read only).
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
WHERE a.zoominfo_id IS NOT NULL
  AND a.company_website IS NOT NULL
  AND a.status = 'Active'
  AND LOWER(a.relationship_types) LIKE '%end%user%'
  AND NOT EXISTS
  (
      SELECT 1
      FROM fact.Opportunity_Term AS ot
      INNER JOIN dim.Term_Status AS ts
          ON ts.term_status_key = ot.term_status_key
      WHERE ot.customer_account_key = a.account_key
        AND ts.is_lcw_term = 1
  )
ORDER BY a.crm_created_on DESC;
