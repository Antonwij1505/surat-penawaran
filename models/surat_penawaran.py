import base64
import requests
from datetime import date, timedelta
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SuratPenawaran(models.Model):
    _name = "surat.penawaran"
    _description = "Surat Penawaran"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_order desc, name desc"

    name = fields.Char(
        string="Nomor Surat",
        required=True,
        copy=False,
        readonly=True,
        default="New",
        tracking=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
        tracking=True,
    )
    opportunity_id = fields.Many2one(
        "crm.lead",
        string="Peluang / CRM Lead",
        tracking=True,
        help="Lead / Opportunity yang terkait dengan surat penawaran ini.",
    )
    company_entity = fields.Selection(
        [
            ("aston", "PT. Aston Graphindo Indonesia"),
            ("solusi_negeri", "PT. AGI Solusi Negeri"),
        ],
        string="Perusahaan (Kop Surat)",
        default="aston",
        required=True,
        tracking=True,
        help="Pilih identitas perusahaan & kop surat resmi yang digunakan untuk penawaran ini.",
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
    user_id = fields.Many2one(
        "res.users",
        string="Salesperson",
        default=lambda self: self.env.user,
        tracking=True,
    )
    date_order = fields.Date(
        string="Tanggal Surat",
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    validity_date = fields.Date(
        string="Berlaku Sampai",
        tracking=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("sent", "Terkirim"),
            ("accepted", "Diterima"),
            ("refused", "Ditolak"),
        ],
        string="Status",
        default="draft",
        tracking=True,
        copy=False,
    )
    pic_name = fields.Char(string="Nama PIC", required=True, tracking=True)
    pic_position = fields.Char(string="Jabatan PIC", tracking=True)
    pic_email = fields.Char(string="Email PIC", tracking=True)
    pic_phone = fields.Char(string="No. HP PIC", tracking=True)
    notes = fields.Text(
        string="Catatan / Syarat & Ketentuan",
        default="1. Harga sudah termasuk pajak dan biaya kirim.\n2. Pembayaran ditransfer ke rekening resmi perusahaan.\n3. Masa berlaku penawaran sesuai dengan tanggal yang tertera.",
    )
    line_ids = fields.One2many(
        "surat.penawaran.line",
        "surat_id",
        string="Detail Produk",
        copy=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    amount_untaxed = fields.Monetary(
        string="Total Sebelum Pajak",
        compute="_compute_amounts",
        store=True,
        currency_field="currency_id",
        tracking=True,
    )
    amount_tax = fields.Monetary(
        string="Pajak",
        compute="_compute_amounts",
        store=True,
        currency_field="currency_id",
    )
    amount_total = fields.Monetary(
        string="Total",
        compute="_compute_amounts",
        store=True,
        currency_field="currency_id",
        tracking=True,
    )

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        if self.partner_id:
            contact = self.partner_id.child_ids.filtered(lambda c: c.type == "contact")[:1]
            if contact and contact.name and contact.name != self.partner_id.name:
                self.pic_name = contact.name
                self.pic_position = contact.function or ""
                self.pic_email = contact.email or self.partner_id.email or ""
                self.pic_phone = contact.mobile or contact.phone or self.partner_id.mobile or self.partner_id.phone or ""
            elif self.opportunity_id:
                info = self.opportunity_id._get_default_pic_info(self.partner_id)
                self.pic_name = info.get("name") or ""
                self.pic_position = info.get("position") or ""
                self.pic_email = info.get("email") or ""
                self.pic_phone = info.get("phone") or ""
            else:
                if not self.partner_id.is_company:
                    self.pic_name = self.partner_id.name
                    self.pic_position = self.partner_id.function or ""
                elif self.pic_name == self.partner_id.name:
                    self.pic_name = ""
                    self.pic_position = ""

    @api.depends("line_ids.price_subtotal", "line_ids.price_tax")
    def _compute_amounts(self):
        for rec in self:
            rec.amount_untaxed = sum(rec.line_ids.mapped("price_subtotal"))
            rec.amount_tax = sum(rec.line_ids.mapped("price_tax"))
            rec.amount_total = rec.amount_untaxed + rec.amount_tax

    def _sync_pic_to_crm_and_partner(self):
        """Otomatis memperbarui data kontak pada CRM Lead dan Res Partner saat Surat Penawaran diisi/diedit."""
        for rec in self:
            # 1. Sync ke CRM Lead
            if rec.opportunity_id:
                lead_vals = {}
                if rec.pic_name and rec.pic_name != rec.opportunity_id.contact_name:
                    lead_vals["contact_name"] = rec.pic_name
                if rec.pic_position is not False and rec.pic_position != (rec.opportunity_id.function or ""):
                    lead_vals["function"] = rec.pic_position or ""
                if rec.pic_phone and rec.pic_phone != rec.opportunity_id.mobile and rec.pic_phone != rec.opportunity_id.phone:
                    lead_vals["mobile"] = rec.pic_phone
                if rec.pic_email and rec.pic_email != rec.opportunity_id.email_from:
                    lead_vals["email_from"] = rec.pic_email
                if lead_vals:
                    rec.opportunity_id.write(lead_vals)

            # 2. Sync ke Res Partner
            if rec.partner_id:
                partner = rec.partner_id
                if partner.is_company:
                    child = partner.child_ids.filtered(lambda c: c.name and c.name == rec.pic_name)[:1]
                    if child:
                        child_vals = {}
                        if rec.pic_position is not False and rec.pic_position != (child.function or ""):
                            child_vals["function"] = rec.pic_position or ""
                        if rec.pic_phone and rec.pic_phone != child.mobile and rec.pic_phone != child.phone:
                            child_vals["mobile"] = rec.pic_phone
                        if rec.pic_email and rec.pic_email != child.email:
                            child_vals["email"] = rec.pic_email
                        if child_vals:
                            child.write(child_vals)
                    elif rec.pic_name and rec.pic_name != partner.name:
                        self.env["res.partner"].create({
                            "parent_id": partner.id,
                            "type": "contact",
                            "name": rec.pic_name,
                            "function": rec.pic_position or "",
                            "mobile": rec.pic_phone or False,
                            "email": rec.pic_email or False,
                        })
                else:
                    partner_vals = {}
                    if rec.pic_name and rec.pic_name != partner.name:
                        partner_vals["name"] = rec.pic_name
                    if rec.pic_position is not False and rec.pic_position != (partner.function or ""):
                        partner_vals["function"] = rec.pic_position or ""
                    if rec.pic_phone and rec.pic_phone != partner.mobile and rec.pic_phone != partner.phone:
                        partner_vals["mobile"] = rec.pic_phone
                    if rec.pic_email and rec.pic_email != partner.email:
                        partner_vals["email"] = rec.pic_email
                    if partner_vals:
                        partner.write(partner_vals)

    def _trigger_crm_p2(self):
        """Otomatis memicu perpindahan lead ke stage P2 (Interest) jika ada penawaran."""
        p2_stage = self.env["crm.stage"].search([
            "|",
            ("name", "ilike", "P2"),
            ("name", "ilike", "Interest")
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

            if lead and p2_stage:
                current_stage_name = lead.stage_id.name or ""
                if "P0" not in current_stage_name and "P1" not in current_stage_name:
                    if lead.stage_id.id != p2_stage.id:
                        lead.stage_id = p2_stage.id
                        lead.message_post(
                            body=f"⚡ **Otomatis Naik ke P2 (Interest)** karena Surat Penawaran resmi **{rec.name}** telah diterbitkan untuk {rec.partner_id.name} (Total: {rec.currency_id.symbol or 'Rp'} {rec.amount_total:,.2f})."
                        )
                if not lead.expected_revenue or lead.expected_revenue == 0:
                    lead.expected_revenue = rec.amount_total

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("surat.penawaran") or "New"
        records = super().create(vals_list)
        for rec in records:
            rec._trigger_crm_p2()
            rec._sync_pic_to_crm_and_partner()
        return records

    def write(self, vals):
        res = super().write(vals)
        pic_fields = {"pic_name", "pic_position", "pic_phone", "pic_email", "partner_id", "opportunity_id"}
        if any(f in vals for f in pic_fields):
            self._sync_pic_to_crm_and_partner()
        return res

    def unlink(self):
        for rec in self:
            if rec.state not in ("draft",):
                raise ValidationError("Anda hanya dapat menghapus Surat Penawaran dengan status Draft.")
        return super().unlink()

    def action_send(self):
        for rec in self:
            rec.write({"state": "sent"})
            rec.message_post(body="Status diubah menjadi **Terkirim**.")
            rec._trigger_crm_p2()

    def action_accept(self):
        for rec in self:
            rec.write({"state": "accepted"})
            rec.message_post(body="Status diubah menjadi **Diterima**.")
            rec._trigger_crm_p2()

    def action_refuse(self):
        for rec in self:
            rec.write({"state": "refused"})
            rec.message_post(body="Status diubah menjadi **Ditolak**.")

    def action_reset_to_draft(self):
        for rec in self:
            rec.write({"state": "draft"})
            rec.message_post(body="Surat Penawaran direset kembali ke **Draft**.")

    def _generate_ai_wa_greeting(self, doc_type="penawaran"):
        """Generate greeting sopan & profesional menggunakan AI yang sedang aktif."""
        try:
            ResConfig = self.env['res.config.settings']
            if hasattr(ResConfig, 'get_active_ai_config'):
                cfg = ResConfig.get_active_ai_config(self.env)
                api_key = cfg.get('api_key')
                base_url = cfg.get('base_url')
                model = cfg.get('model_flash') or 'deepseek-chat'

                if api_key and base_url:
                    endpoint = base_url.rstrip('/') + '/chat/completions'
                    headers = {
                        'Content-Type': 'application/json',
                        'Authorization': f"Bearer {api_key}"
                    }
                    comp_name = "PT. AGI Solusi Negeri" if self.company_entity == "solusi_negeri" else "PT. Aston Graphindo Indonesia"
                    prompt = (
                        f"Buatkan 1-2 kalimat salam pembuka dan pengantar yang sangat sopan, ramah, dan profesional dalam Bahasa Indonesia "
                        f"dari Sales '{self.user_id.name}' ({comp_name}) untuk customer '{self.pic_name}' di instansi '{self.partner_id.name}'. "
                        f"Tujuan: menyampaikan dokumen resmi {doc_type} nomor {self.name}. "
                        f"Hanya kembalikan teks salam pengantar saja (tanpa tanda kutip, tanpa penjelasan)."
                    )
                    payload = {
                        'model': model,
                        'messages': [{'role': 'user', 'content': prompt}],
                        'max_tokens': 100,
                        'temperature': 0.5,
                    }
                    resp = requests.post(endpoint, headers=headers, json=payload, timeout=5)
                    if resp.status_code == 200:
                        content = resp.json().get('choices', [{}])[0].get('message', {}).get('content', '').strip()
                        if content:
                            return content
        except Exception:
            pass

        # Fallback sopan standar jika AI offline
        return f"Semoga Bapak/Ibu dan tim di {self.partner_id.name} senantiasa dalam keadaan sehat dan lancar dalam menjalankan aktivitas."

    def action_send_whatsapp(self):
        """Buka pop-up Wizard Pratinjau Pesan WhatsApp sebelum dikirim."""
        self.ensure_one()
        phone = (self.pic_phone or "").strip()
        if not phone and self.partner_id:
            phone = (self.partner_id.mobile or self.partner_id.phone or "").strip()

        # Generate salam sopan by AI
        ai_greeting = self._generate_ai_wa_greeting(doc_type="Surat Penawaran Harga")

        comp_name = "PT. AGI Solusi Negeri" if self.company_entity == "solusi_negeri" else "PT. Aston Graphindo Indonesia"
        pesan = (
            f"Yth. Bapak/Ibu *{self.pic_name or 'Customer'}* - *{self.partner_id.name}*,\n\n"
            f"{ai_greeting}\n\n"
            f"Bersama ini kami sampaikan dokumen *Surat Penawaran Harga* resmi:\n"
            f"• Nomor Surat: *{self.name}*\n"
            f"• Total Nilai: *{self.currency_id.symbol or 'Rp'} {self.amount_total:,.2f}*\n"
            f"• Masa Berlaku: *s/d {self.validity_date or '-'}*\n\n"
            f"Dokumen Surat Penawaran resmi PDF terlampir. Apabila ada hal yang perlu didiskusikan atau disesuaikan, kami siap membantu.\n\n"
            f"Hormat kami,\n*{self.user_id.name}*\n{comp_name}"
        )

        return {
            "name": "Pratinjau Pesan WhatsApp (Surat Penawaran)",
            "type": "ir.actions.act_window",
            "res_model": "send.wa.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_doc_model": "surat.penawaran",
                "default_doc_id": self.id,
                "default_doc_name": self.name,
                "default_partner_id": self.partner_id.id if self.partner_id else False,
                "default_recipient_name": self.pic_name or (self.partner_id.name if self.partner_id else ""),
                "default_recipient_phone": phone,
                "default_message": pesan,
            },
        }

    def action_send_email(self):
        """Kirim Surat Penawaran via 1 Email Bersama Kantor (marketing@orimax.co.id)."""
        self.ensure_one()
        email_to = (self.pic_email or "").strip()
        if not email_to and self.partner_id:
            email_to = (self.partner_id.email or "").strip()
        if not email_to:
            raise ValidationError("Alamat Email PIC atau Customer belum diisi!")

        company_email = self.company_id.email or "marketing@orimax.co.id"
        comp_name = "PT. AGI Solusi Negeri" if self.company_entity == "solusi_negeri" else "PT. Aston Graphindo Indonesia"
        subject = f"Surat Penawaran Harga - {self.name} - {self.partner_id.name}"
        body_html = f"""
            <p>Yth. Bapak/Ibu <strong>{self.pic_name or 'Customer'}</strong>,</p>
            <p>Bersama ini kami sampaikan dokumen <strong>Surat Penawaran Harga</strong> resmi dari <strong>{comp_name}</strong>:</p>
            <ul>
                <li><strong>Nomor Surat:</strong> {self.name}</li>
                <li><strong>Instansi:</strong> {self.partner_id.name}</li>
                <li><strong>Total Nilai:</strong> {self.currency_id.symbol or 'Rp'} {self.amount_total:,.2f}</li>
                <li><strong>Masa Berlaku:</strong> {self.validity_date or '-'}</li>
            </ul>
            <p>Dokumen penawaran lengkap dapat dilihat pada lampiran PDF terlampir.</p>
            <br/>
            <p>Hormat kami,</p>
            <p><strong>{self.user_id.name}</strong><br/>
            {comp_name}<br/>
            Email: {company_email}</p>
        """

        # Generate PDF report attachment
        pdf_content, _ = self.env['ir.actions.report']._render_qweb_pdf(
            "agi_surat_penawaran.action_report_surat_penawaran", [self.id]
        )
        attachment = self.env['ir.attachment'].create({
            'name': f"Surat_Penawaran_{self.name.replace('/', '_')}.pdf",
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': 'surat.penawaran',
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })

        mail_values = {
            'subject': subject,
            'body_html': body_html,
            'email_from': f"{comp_name} <{company_email}>",
            'email_to': email_to,
            'reply_to': company_email,
            'attachment_ids': [(4, attachment.id)],
        }
        mail = self.env['mail.mail'].sudo().create(mail_values)
        mail.send()

        self.write({"state": "sent"})
        self.message_post(
            body=f"✉️ **Surat Penawaran Dikirim via Email Bersama ({company_email})** ke alamat {email_to} (Attachment PDF terlampir)."
        )
        self._trigger_crm_p2()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Email Terkirim!',
                'message': f"Surat Penawaran berhasil dikirim ke {email_to} menggunakan email resmi kantor.",
                'type': 'success',
                'sticky': False,
            }
        }

    def action_print(self):
        self.ensure_one()
        self._trigger_crm_p2()
        return self.env.ref("agi_surat_penawaran.action_report_surat_penawaran").report_action(self)

    @api.constrains("validity_date", "date_order")
    def _check_dates(self):
        for rec in self:
            if rec.validity_date and rec.date_order and rec.validity_date < rec.date_order:
                raise ValidationError("Tanggal 'Berlaku Sampai' tidak boleh lebih awal dari Tanggal Surat.")


    def action_create_customer_po(self):
        """Buat Form PO Customer secara otomatis dari data Surat Penawaran ini."""
        self.ensure_one()
        po_lines = []
        for line in self.line_ids:
            po_lines.append((0, 0, {
                'sequence': line.sequence,
                'product_id': line.product_id.id if line.product_id else False,
                'name': line.name,
                'price_unit': line.unit_price,
                'product_qty': line.product_uom_qty,
            }))

        vals = {
            'opportunity_id': self.opportunity_id.id if self.opportunity_id else False,
            'partner_id': self.partner_id.id,
            'company_entity': self.company_entity,
            'salesperson_id': self.user_id.id if self.user_id else self.env.user.id,
            'signer_name': self.pic_name or (self.partner_id.name if self.partner_id else "PIC"),
            'signer_job': self.pic_position or "",
            'signer_mobile': self.pic_phone or "",
            'signer_email': self.pic_email or "",
            'line_ids': po_lines,
        }
        po = self.env['customer.po'].create(vals)
        return {
            'name': 'Form PO Customer',
            'type': 'ir.actions.act_window',
            'res_model': 'customer.po',
            'view_mode': 'form',
            'res_id': po.id,
            'target': 'current',
        }
