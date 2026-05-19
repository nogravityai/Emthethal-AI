import React, { useEffect } from 'react';
import { FormBuilder } from '@formio/react';
import 'formiojs/dist/formio.full.css';

export default function FormBuilderWrapper({ schema, onChange }) {
  useEffect(() => {
    const linkId = 'formio-bootstrap-css';
    if (!document.getElementById(linkId)) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = 'https://cdn.jsdelivr.net/npm/bootstrap@4.6.2/dist/css/bootstrap.min.css';
      link.id = linkId;
      document.head.appendChild(link);
    }
  }, []);

  return (
    <div className="formio-builder-wrapper" dir="ltr" style={{background: '#fff', color: '#333', padding: '20px', borderRadius: '8px', minHeight: '800px'}}>
      <FormBuilder 
        form={schema || { display: 'form', components: [] }} 
        onChange={(newSchema) => {
          if (onChange) onChange(newSchema);
        }} 
        options={{
          language: 'ar',
          i18n: {
            ar: {
              'Drag and Drop a form component': 'اسحب واسقط الحقول هنا',
            }
          }
        }}
      />
    </div>
  );
}
