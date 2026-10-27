import base64
import requests
import urllib.parse
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SendWaWizard(models.TransientModel):
    _name = "send.wa.wizard"
    _description = "Preview & Kirim Pesan WhatsApp"

    doc_model = fields.Char(string="Model Dokumen", required=True)
    doc_id = fields.Integer(string="ID Dokumen", required=True)
    doc_name = fields.Char(string="Nomor Dokumen")
    
    partner_id = fields.Many2one("res.partner", string="Customer / Instansi", readonly=True)
    recipient_name = fields.Char(string="Nama Penerima (PIC)", required=True)
    recipient_phone = fields.Char(string="Nomor WhatsApp Tujuan", required=True, help="Format: 08123456789 atau 628123456789")
    
    message = fields.Text(string="Pratinjau Pesan WhatsApp", required=True, help="Anda dapat mengedit isi pesan ini sebelum dikirim.")
    attach_pdf = fields.Boolean(string="Lampirkan File PDF", default=True)

    def action_confirm_send(self):
        """Eksekusi pengiriman pesan setelah ditinjau/diedit oleh sales."""
        self.ensure_one()
        phone = self.recipient_phone.strip()
        clean_phone = "".join(filter(str.isdigit, phone))
        if clean_phone.startswith("0"):
            clean_phone = "62" + clean_phone[1:]

        if not clean_phone:
            raise ValidationError("Nomor WhatsApp tujuan tidak valid!")

        # Ambil record dokumen terkait
        doc = self.env[self.doc_model].browse(self.doc_id)
        if not doc.exists():
            raise ValidationError("Dokumen tidak ditemukan!")

        # 1. Cek konfigurasi Evolution API
        ICP = self.env['ir.config_parameter'].sudo()
        evo_url = ICP.get_param('sirup_base.evolution_api_url')
        evo_key = ICP.get_param('sirup_base.evolution_api_key')

        sales_user = getattr(doc, 'user_id', False) or getattr(doc, 'salesperson_id', False) or self.env.user
        sent_via_evolution = False

        if evo_url and evo_key:
            inst = self.env['evolution.instance'].search([('sales_id', '=', sales_user.id)], limit=1)
            if not inst:
                inst = self.env['evolution.instance'].search([], limit=1)

            if inst and inst.instance_name:
                try:
                    headers = {'apikey': evo_key, 'Content-Type': 'application/json'}
                    
                    # A. Kirim Text
                    send_text_url = f"{evo_url.rstrip('/')}/message/sendText/{inst.instance_name}"
                    resp_text = requests.post(send_text_url, headers=headers, json={'number': clean_phone, 'text': self.message}, timeout=8)

                    # B. Kirim Media PDF jika dicentang
                    if self.attach_pdf:
                        report_xml_id = (
                            "agi_surat_penawaran.action_report_surat_penawaran"
                            if self.doc_model == "surat.penawaran"
                            else "agi_surat_penawaran.action_report_customer_po"
                        )
                        pdf_content, _ = self.env['ir.actions.report']._render_qweb_pdf(report_xml_id, [doc.id])
                        send_media_url = f"{evo_url.rstrip('/')}/message/sendMedia/{inst.instance_name}"
                        comp_name = "PT. AGI Solusi Negeri" if getattr(doc, 'company_entity', False) == 'solusi_negeri' else "PT. Aston Graphindo Indonesia"
                        media_data = {
                            'number': clean_phone,
                            'mediatype': 'document',
                            'mimetype': 'application/pdf',
                            'caption': f"{doc.name} - {comp_name}",
                            'media': base64.b64encode(pdf_content).decode('utf-8'),
                            'fileName': f"{doc.name.replace('/', '_')}.pdf"
                        }
                        requests.post(send_media_url, headers=headers, json=media_data, timeout=12)

                    if resp_text.status_code in [200, 201]:
                        sent_via_evolution = True
                except Exception:
                    sent_via_evolution = False

        # Update status & trigger CRM
        if self.doc_model == "surat.penawaran":
            doc.write({
                "state": "sent",
                "pic_phone": phone,
            })
            if self.recipient_name and not doc.pic_name:
                doc.write({"pic_name": self.recipient_name})
            doc._trigger_crm_p2()
        elif self.doc_model == "customer.po":
            doc.write({
                "signer_mobile": phone,
            })
            if self.recipient_name and not doc.signer_name:
                doc.write({"signer_name": self.recipient_name})
            doc._trigger_crm_p1()

        # Sinkronisasi nomor WhatsApp HANYA ke field mobile (jangan sentuh field phone/telepon kantor)
        lead = getattr(doc, 'opportunity_id', False)
        if lead:
            lead_vals = {}
            if not lead.mobile or lead.mobile != phone:
                lead_vals['mobile'] = phone
            if self.recipient_name and not lead.contact_name:
                lead_vals['contact_name'] = self.recipient_name
            if lead_vals:
                lead.write(lead_vals)

        partner = getattr(doc, 'partner_id', False)
        if partner:
            partner_vals = {}
            if not partner.mobile or partner.mobile != phone:
                partner_vals['mobile'] = phone
            if partner_vals:
                partner.write(partner_vals)

        if sent_via_evolution:
            doc.message_post(body=f"⚡💬 **Pesan WhatsApp & Dokumen Terkirim via Evolution API** ke nomor {clean_phone} ({self.recipient_name}).")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'WhatsApp Terkirim!',
                    'message': f"Pesan berhasil dikirim via WhatsApp ke {clean_phone}.",
                    'type': 'success',
                    'sticky': False,
                }
            }
        else:
            encoded_msg = urllib.parse.quote(self.message)
            wa_url = f"https://wa.me/{clean_phone}?text={encoded_msg}"
            doc.message_post(body=f"💬 **Pesan WhatsApp Dibuka via WhatsApp Web** untuk nomor {clean_phone} ({self.recipient_name}).")
            return {
                "type": "ir.actions.act_url",
                "url": wa_url,
                "target": "new",
            }
