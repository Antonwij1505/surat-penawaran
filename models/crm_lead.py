from odoo import api, fields, models
from datetime import timedelta


class CrmLead(models.Model):
    _inherit = "crm.lead"

    surat_penawaran_ids = fields.One2many(
        "surat.penawaran",
        "opportunity_id",
        string="Surat Penawaran",
    )
    surat_penawaran_count = fields.Integer(
        string="Jumlah Penawaran",
        compute="_compute_surat_penawaran_count",
    )
    customer_po_ids = fields.One2many(
        "customer.po",
        "opportunity_id",
        string="Purchase Order Customer",
    )
    customer_po_count = fields.Integer(
        string="Jumlah PO",
        compute="_compute_customer_po_count",
    )

    @api.depends("surat_penawaran_ids")
    def _compute_surat_penawaran_count(self):
        for lead in self:
            lead.surat_penawaran_count = len(lead.surat_penawaran_ids)

    @api.depends("customer_po_ids")
    def _compute_customer_po_count(self):
        for lead in self:
            lead.customer_po_count = len(lead.customer_po_ids)

    def _ensure_lead_partner(self):
        """Memastikan partner_id terisi dari instansi/lead jika masih kosong."""
        self.ensure_one()
        partner = self.partner_id
        if not partner:
            partner_name = (self.partner_name or self.name or "").strip()
            if partner_name:
                partner = self.env["res.partner"].search([("name", "=ilike", partner_name)], limit=1)
                if not partner:
                    partner = self.env["res.partner"].create({
                        "name": partner_name,
                        "phone": self.phone or False,
                        "mobile": self.mobile or False,
                        "email": self.email_from or False,
                        "street": self.street or False,
                        "street2": self.street2 or False,
                        "city": self.city or False,
                        "state_id": self.state_id.id if self.state_id else False,
                    })
                self.partner_id = partner.id
        return partner

    def _get_default_pic_info(self, partner):
        """Mendapatkan info PIC dari lead/partner secara presisi."""
        self.ensure_one()
        contact_name = (self.contact_name or "").strip()
        partner_name = (self.partner_name or (partner.name if partner else "") or self.name or "").strip()
        function_name = (self.function or "").strip()

        # 1. Jika contact_name sama dengan nama instansi/perusahaan
        if contact_name and (contact_name.lower() == partner_name.lower() or contact_name.lower() == (self.name or "").lower()):
            # Jika function berisi nama orang, gunakan function sebagai nama PIC
            if function_name and len(function_name.split()) <= 4 and not any(w in function_name.lower() for w in ['bagian', 'bidang', 'dinas', 'kantor', 'subag', 'staf', 'staff', 'sekretariat', 'seksi', 'pengadaan', 'logistik', 'pbj', 'tu']):
                pic_name = function_name
                pic_pos = ""
            else:
                pic_name = ""
                pic_pos = function_name
        else:
            pic_name = contact_name
            if function_name and function_name.lower() == contact_name.lower():
                pic_pos = ""
            else:
                pic_pos = function_name

        # Fallback jika pic_name masih kosong dan partner bukan instansi perusahaan biasa
        if not pic_name and partner and not partner.is_company and partner.name.lower() != partner_name.lower():
            pic_name = partner.name

        return {
            "name": pic_name,
            "phone": self.mobile or self.phone or (partner.mobile or partner.phone if partner else ""),
            "email": self.email_from or (partner.email if partner else ""),
            "position": pic_pos,
        }

    def action_create_surat_penawaran(self):
        """Tombol aksi langsung membuat Surat Penawaran dengan data otomatis dari Lead."""
        self.ensure_one()
        partner = self._ensure_lead_partner()
        pic_info = self._get_default_pic_info(partner)
        today = fields.Date.context_today(self)
        validity = today + timedelta(days=30)
        return {
            "name": "Buat Surat Penawaran",
            "type": "ir.actions.act_window",
            "res_model": "surat.penawaran",
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_opportunity_id": self.id,
                "default_partner_id": partner.id if partner else False,
                "default_user_id": self.env.user.id,
                "default_date_order": today,
                "default_validity_date": validity,
                "default_pic_name": pic_info["name"],
                "default_pic_phone": pic_info["phone"],
                "default_pic_email": pic_info["email"],
                "default_pic_position": pic_info["position"],
            },
        }

    def action_create_customer_po(self):
        """Tombol aksi langsung membuat Form PO Customer dengan data otomatis dari Lead."""
        self.ensure_one()
        partner = self._ensure_lead_partner()
        pic_info = self._get_default_pic_info(partner)
        return {
            "name": "Buat Form Purchase Order (PO)",
            "type": "ir.actions.act_window",
            "res_model": "customer.po",
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_opportunity_id": self.id,
                "default_partner_id": partner.id if partner else False,
                "default_salesperson_id": self.env.user.id,
                "default_signer_name": pic_info["name"],
                "default_signer_mobile": pic_info["phone"],
                "default_signer_email": pic_info["email"],
                "default_signer_job": pic_info["position"],
            },
        }

    def action_view_surat_penawaran(self):
        self.ensure_one()
        partner = self._ensure_lead_partner()
        pic_info = self._get_default_pic_info(partner)
        action = self.env["ir.actions.actions"]._for_xml_id("agi_surat_penawaran.action_surat_penawaran")
        action["domain"] = [("opportunity_id", "=", self.id)]
        action["context"] = {
            "default_opportunity_id": self.id,
            "default_partner_id": partner.id if partner else False,
            "default_user_id": self.env.user.id,
            "default_pic_name": pic_info["name"],
            "default_pic_phone": pic_info["phone"],
            "default_pic_email": pic_info["email"],
            "default_pic_position": pic_info["position"],
        }
        return action

    def action_view_customer_po(self):
        self.ensure_one()
        partner = self._ensure_lead_partner()
        pic_info = self._get_default_pic_info(partner)
        action = self.env["ir.actions.actions"]._for_xml_id("agi_surat_penawaran.action_customer_po")
        action["domain"] = [("opportunity_id", "=", self.id)]
        action["context"] = {
            "default_opportunity_id": self.id,
            "default_partner_id": partner.id if partner else False,
            "default_salesperson_id": self.env.user.id,
            "default_signer_name": pic_info["name"],
            "default_signer_mobile": pic_info["phone"],
            "default_signer_email": pic_info["email"],
            "default_signer_job": pic_info["position"],
        }
        return action
