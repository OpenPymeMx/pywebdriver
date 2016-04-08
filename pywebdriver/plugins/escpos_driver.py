# -*- coding: utf-8 -*-
###############################################################################
#
#   Copyright (C) 2014 Akretion (http://www.akretion.com).
#   @author Sébastien BEAU <sebastien.beau@akretion.com>
#   @author Sylvain CALADOR <sylvain.calador@akretion.com>
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU Affero General Public License as
#   published by the Free Software Foundation, either version 3 of the
#   License, or (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU Affero General Public License for more details.
#
#   You should have received a copy of the GNU Affero General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################

from pif import get_public_ip
from pywebdriver import app, config, drivers
from netifaces import interfaces, ifaddresses, AF_INET
from flask_cors import cross_origin
from flask import request, jsonify, render_template
from base_driver import ThreadDriver, check
import simplejson
import usb.core

meta = {
    'name': "ESCPOS Printer",
    'description': """This plugin add the support of ESCPOS Printer for your
        pywebdriver""",
    'require_pip': ['pyxmlescpos'],
    'require_debian': [],
}

try:
    from xmlescpos.printer import Usb, Network
    from xmlescpos.supported_devices import device_list
except ImportError:
    print 'ESCPOS: xmlescpos python library not installed'
else:
    class USBPOSDriver(ThreadDriver, Usb):
        """ ESCPOS Printer Driver class for pywebdriver """

        def __init__(self, *args, **kwargs):
            self.vendor_product = None
            ThreadDriver.__init__(self, args, kwargs)

        def supported_devices(self):
            return device_list

        def connected_usb_devices(self):
            connected = []

            for device in self.supported_devices():
                if usb.core.find(idVendor=device['vendor'], idProduct=device['product']) != None:
                    connected.append(device)

            return connected

        def open_printer(self):

            if self.device:
                return

            try:
                printers = self.connected_usb_devices()
                if printers:
                    printer = printers[0]
                    self.idVendor = printer.get('vendor')
                    self.idProduct = printer.get('product')
                    self.interface = printer.get('interface', 0)
                    self.in_ep = printer.get('in_ep', 0x82)
                    self.out_ep = printer.get('out_ep', 0x01)
                    self.open()
                    self.vendor_product = '%s_%s' % (
                        self.idVendor, self.idProduct
                    )

            except Exception as e:
                self.set_status('error',str(e))

        def open_cashbox(self,printer):
            self.open_printer()
            self.cashdraw(2)
            self.cashdraw(5)

        def get_status(self):
            messages = []
            self.open_printer()
            if not self.device:
                status = 'disconnected'
            else:
                try:
                    res = self.get_printer_status()
                    if res['printer']['online']:
                        status = 'connected'
                    else:
                        status = 'connecting'

                    if res['printer']['status_error']:
                        status = 'error'
                        messages.append('Error code: %i' % res['printer']['status_error'])

                except Exception, err:
                    status = 'error'
                    self.device = False
                    messages.append('Error: %s' % err)

            return {
                'status': status,
                'messages': messages,
            }

        def printstatus(self,eprint):
            #<PyWebDriver> Full refactoring of the function to allow
            # localisation and to make more easy the search of the ip

            self.open_printer()
            ip = get_public_ip()

            if not ip:
                msg = _(
                    """ERROR: Could not connect to LAN<br/><br/>"""
                    """Please check that your system is correc-<br/>"""
                    """tly connected with a network cable,<br/>"""
                    """ that the LAN is setup with DHCP, and<br/>"""
                    """that network addresses are available""")
                self.receipt('<div>'+msg+'</div>')
                self.cut()
            else:
                addr_lines = []
                for ifaceName in interfaces():
                    addresses = [i['addr'] for i in ifaddresses(ifaceName).setdefault(AF_INET, [{'addr':'No IP addr'}] )]
                    addr_lines.append(
                        '<p>'+','.join(addresses) + ' (' + ifaceName + ')' + '</p>'
                    )
                msg = _("""
                       <div align="center">
                            <h4>PyWebDriver Software Status</h4>
                            <br/><br/>
                            <h5>IP Addresses:</h5>
                            %s<br/>
                            %s<br/>
                            Port: %i
                       </div>
                """) % (
                    ip + ' (' + _(u'Public') + ')',
                    ''.join(addr_lines),
                    config.getint('flask', 'port'),
                )
                self.receipt(msg)


    class NTWPOSDriver(ThreadDriver, Network):
        """ ESCPOS Network Printer Driver class for pywebdriver """

        def __init__(self, *args, **kwargs):
            ThreadDriver.__init__(self, args, kwargs)
            self.host = config.get('escpos_driver', 'device_host')
            self.port = int(config.get('escpos_driver', 'device_port'))
            
        def open_printer(self):
            """ Network printer uses sockets that fails on thread
            so we wait to open the printer until the moment its is
            necessary, means when sending raw commands """
            pass
        
        def _raw(self, msg):
            """ Each command we send to printer must open and close
            connection for prevent Broken pipes """
            try:
                self.open()
                self.device.send(msg)
                self.device.close()
            except Exception as e:
                self.set_status('error',str(e))
                
        def get_status(self):
            messages = []
            self.open_printer()

            if not self.device:
                status = 'disconnected'
            else:
                try:
                    res = self.get_printer_status()
                    if res['printer']['online']:
                        status = 'connected'
                    else:
                        status = 'connecting'

                    if res['printer']['status_error']:
                        status = 'error'
                        messages.append('Error code: %i' % res['printer']['status_error'])

                except Exception, err:
                    status = 'error'
                    self.device = False
                    messages.append('Error: %s' % err)

            return {
                'status': status,
                'messages': messages,
            }
    
    if config.get('escpos_driver', 'device_type') == 'usb':
        driver = USBPOSDriver(app.config)
    elif config.get('escpos_driver', 'device_type') == 'network':
        driver = NTWPOSDriver(app.config)
    drivers['escpos'] = driver
    installed=True

    @app.route(
            '/hw_proxy/print_xml_receipt',
            methods=['POST', 'GET', 'PUT', 'OPTIONS'])
    @cross_origin(headers=['Content-Type'])
    def print_xml_receipt_json():
        """ For Odoo 8.0+"""

        driver.open_printer()
        receipt = request.json['params']['receipt']
        driver.push_task('receipt', receipt)

        return jsonify(jsonrpc='2.0', result=True)

    @app.route('/print_status.html', methods=['GET'])
    @cross_origin()
    def print_status_http():
        driver.push_task('printstatus')
        return render_template('print_status.html')

    @app.route('/hw_proxy/open_cashbox', methods=['POST', 'GET', 'PUT', 'OPTIONS'])
    @cross_origin(headers=['Content-Type'])
    def open_cashbox():
        driver.push_task('open_cashbox')
        return jsonify(jsonrpc='2.0', result=True)

