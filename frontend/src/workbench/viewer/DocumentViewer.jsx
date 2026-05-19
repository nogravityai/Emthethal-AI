import React from 'react';

/**
 * Dumb component that just displays the document image/canvas 
 * and provides a coordinate system for the OverlayManager.
 */
export default function DocumentViewer({ imageUrl, width, height, children }) {
    return (
        <div 
            className="relative bg-gray-900 border border-gray-700 shadow-2xl overflow-auto"
            style={{ 
                width: '100%', 
                height: '800px',
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'flex-start'
            }}
        >
            <div 
                className="relative bg-white"
                style={{ 
                    width: width || 1000, 
                    height: height || 1000,
                    transformOrigin: 'top left',
                    boxShadow: '0 0 20px rgba(0,0,0,0.5)'
                }}
            >
                {/* Background Image */}
                {imageUrl ? (
                    <img 
                        src={imageUrl} 
                        alt="Document" 
                        style={{ width: '100%', height: '100%', objectFit: 'contain' }} 
                    />
                ) : (
                    <div className="w-full h-full flex items-center justify-center text-gray-300 border-2 border-dashed border-gray-200">
                        No Document Image Available
                    </div>
                )}
                
                {/* Overlays rendered on top of the document coordinate space */}
                <div className="absolute inset-0 pointer-events-none">
                    {children}
                </div>
            </div>
        </div>
    );
}
