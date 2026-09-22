import base64
import requests
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CustomerPO(models.Model):
    _name = "customer.po"
    _description = "Form Purchase Order Customer"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_order desc, name desc"

    name = fields.Char(
        string="Nomor PO",
        required=False,
        copy=False,
        readonly=False,
        default="",
        tracking=True,
    )
    company_entity = fields.Selection(
        [
            ("aston", "PT. Aston Graphindo Indonesia"),
            ("solusi_negeri", "PT. AGI Solusi Negeri"),
        ],
        string="Perusahaan (Kop / Tujuan PO)",
        default="aston",
        required=True,
        tracking=True,
        help="Pilih identitas perusahaan penerima pesanan.",
    )
    company_entity_logo = fields.Binary(
        string="Logo Perusahaan PDF",
        compute="_compute_company_entity_logo",
    )

    @api.depends("company_entity", "company_id")
    def _compute_company_entity_logo(self):
        import os
        import base64
        addon_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rec in self:
            if rec.company_entity == "solusi_negeri":
                logo_file = os.path.join(addon_path, "static", "description", "Logo-ASN-.jpg")
            else:
                logo_file = os.path.join(addon_path, "static", "description", "logo.jpg")

            if os.path.exists(logo_file):
                with open(logo_file, "rb") as f:
                    rec.company_entity_logo = base64.b64encode(f.read())
            else:
                rec.company_entity_logo = rec.company_id.logo
    place = fields.Char(
        string="Tempat",
        tracking=True,
    )
    date_order = fields.Date(
        string="Tanggal PO",
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )

    # Vendor Info (PT. Aston Graphindo Indonesia or company)
    company_id = fields.Many2one(
        "res.company",
        string="Perusahaan Penerima PO",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        string="Currency",
        store=True,
        readonly=True,
    )

    # Pemesan / Bertandatangan di bawah ini
    signer_name = fields.Char(string="Nama Lengkap Penandatangan", required=True, tracking=True)
    signer_job = fields.Char(string="Jabatan", tracking=True)
    signer_mobile = fields.Char(string="No. Handphone", tracking=True)
    signer_email = fields.Char(string="Alamat E-mail", tracking=True)

    # Instansi / Tempat Bekerja
    partner_id = fields.Many2one(
        "res.partner",
        string="Instansi / Customer",
        required=True,
        tracking=True,
    )
    opportunity_id = fields.Many2one(
        "crm.lead",
        string="Peluang / CRM Lead",
        tracking=True,
        help="Lead / Opportunity yang terkait dengan Form PO ini.",
    )
    instansi_name = fields.Char(string="Nama Instansi", tracking=True)
    instansi_address = fields.Text(string="Alamat Instansi", tracking=True)
    instansi_phone = fields.Char(string="Nomer Telepon Instansi", tracking=True)

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        if self.partner_id:
            contact = self.partner_id.child_ids.filtered(lambda c: c.type == "contact")[:1]
            if contact and contact.name and contact.name != self.partner_id.name:
                self.signer_name = contact.name
                self.signer_job = contact.function or ""
                self.signer_email = contact.email or self.partner_id.email or ""
                self.signer_mobile = contact.mobile or contact.phone or self.partner_id.mobile or self.partner_id.phone or ""
            elif self.opportunity_id:
                info = self.opportunity_id._get_default_pic_info(self.partner_id)
                self.signer_name = info.get("name") or ""
                self.signer_job = info.get("position") or ""
                self.signer_email = info.get("email") or ""
                self.signer_mobile = info.get("phone") or ""
            else:
                if not self.partner_id.is_company:
                    self.signer_name = self.partner_id.name
                    self.signer_job = self.partner_id.function or ""
                elif self.signer_name == self.partner_id.name:
                    self.signer_name = ""
                    self.signer_job = ""

            self.instansi_name = self.partner_id.name
            address_parts = [
                self.partner_id.street,
                self.partner_id.street2,
                self.partner_id.city,
                self.partner_id.state_id.name if self.partner_id.state_id else "",
                self.partner_id.zip,
            ]
            self.instansi_address = ", ".join([p for p in address_parts if p])
            self.instansi_phone = self.partner_id.phone or self.partner_id.mobile or ""
            self.place = self.partner_id.city or (self.partner_id.state_id.name if self.partner_id.state_id else "")

    def _sync_signer_to_crm_and_partner(self):
        """Otomatis memperbarui data kontak pada CRM Lead dan Res Partner saat Form PO diisi/diedit."""
        for rec in self:
            # 1. Sync ke CRM Lead
            if rec.opportunity_id:
                lead_vals = {}
                if rec.signer_name and rec.signer_name != rec.opportunity_id.contact_name:
                    lead_vals["contact_name"] = rec.signer_name
                if rec.signer_job is not False and rec.signer_job != (rec.opportunity_id.function or ""):
                    lead_vals["function"] = rec.signer_job or ""
                if rec.signer_mobile and rec.signer_mobile != rec.opportunity_id.mobile and rec.signer_mobile != rec.opportunity_id.phone:
                    lead_vals["mobile"] = rec.signer_mobile
                if rec.signer_email and rec.signer_email != rec.opportunity_id.email_from:
                    lead_vals["email_from"] = rec.signer_email
                if lead_vals:
                    rec.opportunity_id.write(lead_vals)

            # 2. Sync ke Res Partner
            if rec.partner_id:
                partner = rec.partner_id
                if partner.is_company:
                    child = partner.child_ids.filtered(lambda c: c.name and c.name == rec.signer_name)[:1]
                    if child:
                        child_vals = {}
                        if rec.signer_job is not False and rec.signer_job != (child.function or ""):
                            child_vals["function"] = rec.signer_job or ""
                        if rec.signer_mobile and rec.signer_mobile != child.mobile and rec.signer_mobile != child.phone:
                            child_vals["mobile"] = rec.signer_mobile
                        if rec.signer_email and rec.signer_email != child.email:
                            child_vals["email"] = rec.signer_email
                        if child_vals:
                            child.write(child_vals)
                    elif rec.signer_name and rec.signer_name != partner.name:
                        self.env["res.partner"].create({
                            "parent_id": partner.id,
                            "type": "contact",
                            "name": rec.signer_name,
                            "function": rec.signer_job or "",
                            "mobile": rec.signer_mobile or False,
                            "email": rec.signer_email or False,
                        })
                else:
                    partner_vals = {}
                    if rec.signer_name and rec.signer_name != partner.name:
                        partner_vals["name"] = rec.signer_name
                    if rec.signer_job is not False and rec.signer_job != (partner.function or ""):
                        partner_vals["function"] = rec.signer_job or ""
                    if rec.signer_mobile and rec.signer_mobile != partner.mobile and rec.signer_mobile != partner.phone:
                        partner_vals["mobile"] = rec.signer_mobile
                    if rec.signer_email and rec.signer_email != partner.email:
                        partner_vals["email"] = rec.signer_email
                    if partner_vals:
                        partner.write(partner_vals)

    # Ketentuan & Syarat
    payment_term_desc = fields.Char(
        string="Pelunasan Pembayaran",
        default="30 Hari terhitung sejak barang diterima",
    )
    payment_due_date = fields.Date(string="Tanggal Jatuh Tempo")
    transaction_method = fields.Char(
        string="Metode Transaksi",
        default="Pembelian Langsung",
    )

    # Checkbox Include Tax & Shipping
    include_ppn = fields.Boolean(string="Include PPN", default=True)
    include_pph = fields.Boolean(string="Include PPH", default=False)
    include_shipping = fields.Boolean(string="Include Biaya Kirim", default=True)

    court_domicile = fields.Char(
        string="Domisili Hukum Pengadilan",
        default="Pengadilan Negeri Karanganyar",
    )
    notes_other = fields.Text(string="Lainnya")

    # Signatures Info
    salesperson_id = fields.Many2one(
        "res.users",
        string="Salesman (Penerima Pesanan)",
        default=lambda self: self.env.user,
        tracking=True,
    )
    salesperson_name = fields.Char(string="Nama Salesman")
    approver_name = fields.Char(
        string="Pesanan Disetujui Oleh (PT. Aston Graphindo Indonesia)",
        default="Febriyan Adi Garuda Sakti",
    )

    @api.onchange("salesperson_id")
    def _onchange_salesperson_id(self):
        if self.salesperson_id:
            self.salesperson_name = self.salesperson_id.name

    # Lines
    line_ids = fields.One2many(
        "customer.po.line",
        "po_id",
        string="Rincian Barang",
        copy=True,
    )

    # Totals
    amount_total = fields.Monetary(
        string="Total",
        compute="_compute_amount_total",
        store=True,
        currency_field="currency_id",
        tracking=True,
    )
    amount_total_words = fields.Char(
        string="Terbilang",
        compute="_compute_amount_total_words",
        store=True,
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Disetujui / Confirmed"),
            ("cancel", "Batal"),
        ],
        string="Status",
        default="draft",
        tracking=True,
        copy=False,
    )

    @api.depends("line_ids.price_total")
    def _compute_amount_total(self):
        for rec in self:
            rec.amount_total = sum(rec.line_ids.mapped("price_total"))

    @api.depends("amount_total", "currency_id")
    def _compute_amount_total_words(self):
        for rec in self:
            if rec.amount_total:
                words = rec.currency_id.with_context(lang="id_ID").amount_to_text(rec.amount_total) if rec.currency_id else ""
                if not words or "Rupiah" not in words:
                    # Fallback Bahasa Indonesia terbilang sederhana
                    words = rec._amount_to_text_id(rec.amount_total)
                rec.amount_total_words = words
            else:
                rec.amount_total_words = ""

    def _amount_to_text_id(self, amount):
        units = ["", "Satu", "Dua", "Tiga", "Empat", "Lima", "Enam", "Tujuh", "Delapan", "Sembilan", "Sepuluh", "Sebelas"]
        def _say(n):
            if n < 12:
                return units[int(n)]
            elif n < 20:
                return _say(n - 10) + " Belas"
            elif n < 100:
                return _say(n // 10) + " Puluh " + _say(n % 10)
            elif n < 200:
                return "Seratus " + _say(n - 100)
            elif n < 1000:
                return _say(n // 100) + " Ratus " + _say(n % 100)
            elif n < 2000:
                return "Seribu " + _say(n - 1000)
            elif n < 1000000:
                return _say(n // 1000) + " Ribu " + _say(n % 1000)
            elif n < 1000000000:
                return _say(n // 1000000) + " Juta " + _say(n % 1000000)
            elif n < 1000000000000:
                return _say(n // 1000000000) + " Miliar " + _say(n % 1000000000)
            return str(n)
        
        val = int(round(amount))
        res = _say(val).strip()
        import re
        res = re.sub(r"\s+", " ", res)
        return res + " Rupiah"

    def _trigger_crm_p1(self):
        """Otomatis memicu perpindahan lead ke stage P1 (Desire / Hot) saat Form PO dibuat / disiapkan."""
        p1_stage = self.env["crm.stage"].search([
            "|",
            ("name", "ilike", "P1"),
            ("name", "ilike", "Desire")
        ], limit=1)
        for rec in self:
            lead = rec.opportunity_id
            if not lead and rec.partner_id:
                lead = self.env["crm.lead"].search([
                    ("partner_id", "=", rec.partner_id.id),
                    ("type", "=", "opportunity"),
                    ("probability", "<", 100),
                ], limit=1)
                if lead:
                    rec.opportunity_id = lead.id

            if lead and p1_stage:
                current_stage_name = lead.stage_id.name or ""
                if "P0" not in current_stage_name:
                    if lead.stage_id.id != p1_stage.id:
                        lead.stage_id = p1_stage.id
                        po_num = rec.name or "(Draft)"
                        lead.message_post(
                            body=f"🔥 **HOT LEAD! Otomatis Naik ke P1 (Desire / Hot)** karena Form Purchase Order (PO) Customer telah dibuat (Nomor: {po_num}, Total: {rec.currency_id.symbol or 'Rp'} {rec.amount_total:,.2f}). Menunggu konfirmasi / tanda tangan customer."
                        )
                if not lead.expected_revenue or lead.expected_revenue == 0:
                    lead.expected_revenue = rec.amount_total

    def _trigger_crm_p0(self):
        """Otomatis memicu perpindahan lead ke stage P0 (Deal / Won) saat Form PO disetujui / confirmed."""
        p0_stage = self.env["crm.stage"].search([
            "|",
            ("name", "ilike", "P0"),
            ("name", "ilike", "Deal")
        ], limit=1)
        for rec in self:
            lead = rec.opportunity_id
            if not lead and rec.partner_id:
                lead = self.env["crm.lead"].search([
                    ("partner_id", "=", rec.partner_id.id),
                    ("type", "=", "opportunity"),
                ], limit=1)
                if lead:
                    rec.opportunity_id = lead.id

            if lead and p0_stage:
                if lead.stage_id.id != p0_stage.id:
                    lead.stage_id = p0_stage.id
                    lead.probability = 100
                    po_num = rec.name or "(Terkonfirmasi)"
                    lead.message_post(
                        body=f"🎉 **DEAL! Otomatis Naik ke P0 (Deal / Won)** karena Form Purchase Order (PO) Customer telah disetujui / Confirmed (Nomor: {po_num}, Total: {rec.currency_id.symbol or 'Rp'} {rec.amount_total:,.2f})."
                    )
                if not lead.expected_revenue or lead.expected_revenue == 0:
                    lead.expected_revenue = rec.amount_total

    @api.model
    def create(self, vals):
        if vals.get("name", "New") == "New":
            vals["name"] = self.env["ir.sequence"].next_by_code("customer.po") or "New"
        rec = super(CustomerPO, self).create(vals)
        rec._trigger_crm_p1()
        rec._sync_signer_to_crm_and_partner()
        return rec

    def write(self, vals):
        res = super(CustomerPO, self).write(vals)
        signer_fields = {"signer_name", "signer_job", "signer_mobile", "signer_email", "partner_id", "opportunity_id"}
        if any(f in vals for f in signer_fields):
            self._sync_signer_to_crm_and_partner()
        return res

    def action_print(self):
        self.ensure_one()
        self._trigger_crm_p1()
        return self.env.ref("agi_surat_penawaran.action_report_customer_po").report_action(self)

    def _generate_ai_po_greeting(self):
        """Generate greeting sopan & profesional untuk Purchase Order by AI."""
        try:
            ResConfig = self.env['res.config.settings']
            if hasattr(ResConfig, 'get_active_ai_config'):
                cfg = ResConfig.get_active_ai_config(self.env)
                api_key = cfg.get('api_key')
                base_url = cfg.get('base_url')
                model = cfg.get('model_flash') or 'deepseek-chat'

                if api_key and base_url:
                    endpoint = base_url.rstrip('/') + '/chat/completions'
                    headers = {'Content-Type': 'application/json', 'Authorization': f"Bearer {api_key}"}
                    prompt = (
                        f"Buatkan 1 kalimat salam pembuka dan pengantar yang sangat sopan, ramah, dan profesional dalam Bahasa Indonesia "
                        f"dari Sales '{self.salesperson_id.name}' (PT. Aston Graphindo Indonesia) untuk pemesan '{self.signer_name}' di instansi '{self.partner_id.name}'. "
                        f"Tujuan: menyampaikan dokumen resmi Form Purchase Order (PO) nomor {self.name or 'Draft'}. "
                        f"Hanya kembalikan kalimat salam pengantar saja (tanpa tanda kutip, tanpa penjelasan)."
                    )
                    payload = {'model': model, 'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': 100, 'temperature': 0.5}
                    resp = requests.post(endpoint, headers=headers, json=payload, timeout=5)
                    if resp.status_code == 200:
                        content = resp.json().get('choices', [{}])[0].get('message', {}).get('content', '').strip()
                        if content:
                            return content
        except Exception:
            pass
        return f"Terima kasih atas kepercayaan Bapak/Ibu dan seluruh jajaran di {self.partner_id.name} kepada perusahaan kami."

    def action_send_whatsapp(self):
        """Buka pop-up Wizard Pratinjau Pesan WhatsApp sebelum Form PO dikirim."""
        self.ensure_one()
        phone = (self.signer_mobile or self.instansi_phone or "").strip()
        if not phone and self.partner_id:
            phone = (self.partner_id.mobile or self.partner_id.phone or "").strip()

        po_num = self.name or "(Draft PO)"
        ai_greeting = self._generate_ai_po_greeting()

        pesan = (
            f"Yth. Bapak/Ibu *{self.signer_name or 'Pemesan'}* - *{self.partner_id.name}*,\n\n"
            f"{ai_greeting}\n\n"
            f"Bersama ini kami lampirkan dokumen resmi *Form Purchase Order (PO)* untuk pengadaan kebutuhan kantor:\n"
            f"• Nomor PO: *{po_num}*\n"
            f"• Total Nilai: *{self.currency_id.symbol or 'Rp'} {self.amount_total:,.2f}*\n\n"
            f"Dokumen Purchase Order PDF terlampir. Mohon untuk dicek dan dikonfirmasi kembali. Terima kasih atas kerja samanya.\n\n"
            f"Hormat kami,\n*{self.salesperson_id.name}*\nPT. Aston Graphindo Indonesia"
        )

        return {
            "name": "Pratinjau Pesan WhatsApp (Purchase Order)",
            "type": "ir.actions.act_window",
            "res_model": "send.wa.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_doc_model": "customer.po",
                "default_doc_id": self.id,
                "default_doc_name": po_num,
                "default_partner_id": self.partner_id.id if self.partner_id else False,
                "default_recipient_name": self.signer_name or (self.partner_id.name if self.partner_id else ""),
                "default_recipient_phone": phone,
                "default_message": pesan,
                "default_attach_pdf": True,
            },
        }

    def action_send_email(self):
        """Kirim Form Purchase Order via 1 Email Bersama Kantor (marketing@orimax.co.id)."""
        self.ensure_one()
        email_to = (self.signer_email or "").strip()
        if not email_to and self.partner_id:
            email_to = (self.partner_id.email or "").strip()
        if not email_to:
            raise ValidationError("Alamat Email Penandatangan atau Instansi belum diisi!")

        company_email = self.company_id.email or "marketing@orimax.co.id"
        po_num = self.name or "Draft PO"
        subject = f"Form Purchase Order (PO) - {po_num} - {self.partner_id.name}"
        body_html = f"""
            <p>Yth. Bapak/Ibu <strong>{self.signer_name or 'Pemesan'}</strong>,</p>
            <p>Bersama ini kami lampirkan dokumen <strong>Form Purchase Order (PO)</strong> untuk pengadaan kebutuhan kantor di {self.partner_id.name}:</p>
            <ul>
                <li><strong>Nomor PO:</strong> {po_num}</li>
                <li><strong>Instansi:</strong> {self.partner_id.name}</li>
                <li><strong>Total Nilai:</strong> {self.currency_id.symbol or 'Rp'} {self.amount_total:,.2f}</li>
            </ul>
            <p>Dokumen Purchase Order lengkap dapat dilihat pada lampiran PDF terlampir.</p>
            <br/>
            <p>Hormat kami,</p>
            <p><strong>{self.salesperson_id.name}</strong><br/>
            PT. Aston Graphindo Indonesia<br/>
            Email: {company_email}</p>
        """

        import base64
        pdf_content, _ = self.env['ir.actions.report']._render_qweb_pdf(
            "agi_surat_penawaran.action_report_customer_po", [self.id]
        )
        attachment = self.env['ir.attachment'].create({
            'name': f"Purchase_Order_{po_num.replace('/', '_')}.pdf",
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': 'customer.po',
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })

        mail_values = {
            'subject': subject,
            'body_html': body_html,
            'email_from': f"PT. Aston Graphindo Indonesia <{company_email}>",
            'email_to': email_to,
            'reply_to': company_email,
            'attachment_ids': [(4, attachment.id)],
        }
        mail = self.env['mail.mail'].sudo().create(mail_values)
        mail.send()

        self.message_post(
            body=f"✉️ **Form PO Dikirim via Email Bersama ({company_email})** ke alamat {email_to} (Attachment PDF terlampir)."
        )
        self._trigger_crm_p1()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Email Terkirim!',
                'message': f"Form Purchase Order berhasil dikirim ke {email_to}.",
                'type': 'success',
                'sticky': False,
            }
        }

    def action_confirm(self):
        self.write({"state": "confirmed"})
        self._trigger_crm_p0()

    def action_cancel(self):
        self.write({"state": "cancel"})

    def action_draft(self):
        self.write({"state": "draft"})
