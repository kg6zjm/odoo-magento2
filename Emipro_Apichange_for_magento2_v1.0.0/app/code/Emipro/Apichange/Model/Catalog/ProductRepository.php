<?php

namespace Emipro\Apichange\Model\Catalog;

class ProductRepository extends \Magento\Catalog\Model\ProductRepository
{
    protected function initializeProductData(array $productData, $createNew)
    {
        $_websiteIds = array();
        if (!$createNew) {
            $product = $this->get($productData['sku']);
            $_websiteIds = $product->getWebsiteIds();
        }

        $product = parent::initializeProductData($productData, $createNew);

        // If product is new, we will store all the values on global scope
        if ($createNew) {
            $productId = $product->getId();
            if (!$productId) {
                $product->setStoreId(0);
                $product->setWebsiteIds(array());
            }
        } else {

            $product->setWebsiteIds($_websiteIds);
            if (!isset($productData['media_gallery_entries'])) {
                $attid = $product->getAttributeSetId();
                $product->reset();
                $product->setAttributeSetId($attid);
                foreach ($productData as $key => $value) {
                    $product->setData($key, $value);
                }
            }
        }
        return $product;
    }

}
